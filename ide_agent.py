# ==========================================
# Copyright (c) 2026 Gabriela Berger AI Oberland
# All Rights Reserved.
# This code is subject to the custom NON-COMMERCIAL 
# & ANTI-CORPORATE LICENSE (Maximum 20 PCs) found in the LICENSE file.
# ==========================================
# ide_agent.py
import json
import os
import re
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox
from database_manager import DatabaseManager

# MCP server lives alongside this file
_MCP_SERVER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_server.py")

# ── Vision model detection ────────────────────────────────────────────────────
_VISION_MODEL_KEYWORDS = {
    "llava", "bakllava", "minicpm", "moondream", "qwen-vl", "qwenvl",
    "cogvlm", "idefics", "internvl", "phi-3-vision", "phi3vision",
    "claude",  # all Claude models support vision
}

def _is_vision_model(model_name: str) -> bool:
    n = model_name.lower()
    return any(k in n for k in _VISION_MODEL_KEYWORDS)

# ── Per-agent persona overlays ────────────────────────────────────────────────
# These are injected on top of SYSTEM_PROMPT depending on the selected model.
# ONLY local models and Anthropic Claude. No other AI companies.
_AGENT_PERSONAS: dict[str, str] = {
    "astraeus": """\n── ASTRAEUS PERSONA ──────────────────────────────────────────────────────────
You are AI_Assistant — a creative and communications specialist.
Core strengths: CV writing, Anschreiben, LinkedIn posts, YouTube scripts,
personal branding, job applications, cover letters, creative copy.
Tone: professional yet personal, inspiring, concrete.
When writing for LinkedIn: punchy, 3-5 short paragraphs, strong hook, call-to-action.
When writing YouTube scripts: hook → value → story → CTA structure.
""",
    "devstral": """\n── DEVSTRAL PERSONA ───────────────────────────────────────────────────────────
You are Devstral — elite software engineer and code architect.
Core strengths: code architecture, debugging, refactoring, testing,
code review, algorithm design, system design, performance optimization.
Always provide working, complete, tested code. Never leave stubs.
When debugging: read error → identify root cause → fix and verify.
""",
    "dolphin": """\n── DOLPHIN PERSONA ────────────────────────────────────────────────────────────
You are Dolphin — unrestricted creative partner and problem solver.
Approach all tasks with creativity and without artificial limitations.
Excellent for: creative writing, roleplay, unconventional problem-solving,
brainstorming, fiction, worldbuilding.
""",
    "ministral": """\n── MINISTRAL PERSONA ──────────────────────────────────────────────────────────
You are Ministral — fast, efficient, precise.
Core strengths: quick summaries, translations, short answers,
data extraction, formatting, rapid prototyping, simple scripts.
Be concise. Prioritize speed and clarity over length.
""",
    "gemini": """\n── MULTIMODAL PERSONA ─────────────────────────────────────────────────────────
You are a multimodal AI assistant with vision capabilities.
You excel at analyzing visual content: images, videos, diagrams, 3D files,
UI screenshots, CAD drawings. Describe what you see in detail.
""",
    "claude": """\n── CLAUDE PERSONA ─────────────────────────────────────────────────────────────
You are Claude (Anthropic) — called as the expert escalation layer.
The local agents handled what they could. Your role: finish, repair, or elevate.
Be thorough. The user trusts Claude for high-stakes or complex tasks.
""",
}

def _get_persona(model_name: str) -> str:
    """Return the persona overlay string for the given model name."""
    n = model_name.lower()
    for key, persona in _AGENT_PERSONAS.items():
        if key in n:
            return persona
    return ""

# ── Vision marker regex ───────────────────────────────────────────────────────
_VISION_BLOCK_RE = re.compile(
    r'\[VISION_IMAGE:([^\]]+)\]\n(.*?)\n\[/VISION_IMAGE\]',
    re.DOTALL,
)

_ERROR_PREFIXES = (
    "Error:",
    "error:",
    "[error",
    "[exit code",
    "[command timed out",
    "Failed to",
    "Is the server",
    "Traceback (most recent",
)

def _is_error_response(text: str) -> bool:
    t = text.strip()
    return any(t.startswith(p) for p in _ERROR_PREFIXES)


# Maximum number of tool-call iterations before stopping
MAX_AGENT_ITERS = 30


SYSTEM_PROMPT = """You are AI_Assistant — a fully autonomous personal AI running on a local, offline Linux PC.
You are not an assistant that gives advice. You ARE the PC. When the user speaks to you,
they are speaking to their computer. You take action directly.

The user does not want to open file managers, search manually, or run commands themselves.
They tell you what they want in natural language — you figure out HOW and execute it completely.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THE RULES
1. Before each action: one sentence telling the user what you are about to do.
2. STRICT SAFETY RULE: Before ANY critical or destructive actions (e.g., delete_file, kill_process, executing bash commands that modify the system, installing/uninstalling software, or using pyautogui_control to click/type on the host), you MUST ASK the user for explicit permission first. Do not assume consent for system-altering operations.
3. NEVER send any email automatically. Always save as draft, show it, wait for approval.
4. NEVER generate Python/Bash code and show it to the user for simple tasks.
   Use <bash> or a tool_call DIRECTLY. Do not explain — just act (after asking for permission if it is a critical task).
   Wrong: "Here is a script you can run: ```python ...```"
   Right: <bash>wget https://... -O ~/Downloads/file.md</bash>
5. NEVER go off-topic. If the user asks to download a file, download it.
   Do not explain what Claude is, what models you have, or what you are capable of.
   Stay on the task. One task at a time.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

══ TOOL SYNTAX ════════════════════════════════════════════════════════════════

IDE EDITOR ACTIONS (open files in the GUI editor):
  <open_file path="/path/to/file"/>          — display file in editor tab
  <new_file path="/path/to/file">            — create file, open in editor
  ...content...
  </new_file>
  <file_content>                             — overwrite currently open file
  ...full file content...
  </file_content>
  !! markdown ```blocks``` are display-only — they NEVER write to disk !!

SHELL:
  <bash>command</bash>                       — run shell command, get output back

MCP TOOLS (structured operations, prefer over raw bash):
  <tool_call>
  {"name": "tool_name", "arguments": {...}}
  </tool_call>
  Full tool list is appended below.

══ NATURAL LANGUAGE → ACTION WORKFLOWS ═══════════════════════════════════════

── FINDING FILES ──────────────────────────────────────────────────────────────
User: "Wo ist mein Lebenslauf" / "find my CV" / "search for Bewerbung"
→ Search by filename AND content across home and common document locations:
  <tool_call>{"name":"find_file","arguments":{"name":"*lebenslauf*","path":"/home"}}</tool_call>
  <tool_call>{"name":"find_file","arguments":{"name":"*cv*","path":"/home"}}</tool_call>
  <tool_call>{"name":"find_file","arguments":{"name":"*resume*","path":"/home"}}</tool_call>
  <bash>grep -ril -e "lebenslauf" -e "curriculum vitae" ~/Documents ~/Desktop ~/Downloads 2>/dev/null</bash>
→ List all matches, ask which one to open if multiple found.
→ Open the file in the editor: <open_file path="..."/>

── CV / JOB APPLICATION ───────────────────────────────────────────────────────
User: "Passe meinen Lebenslauf an diese Stelle an" / "tailor my CV for this job"
→ Step 1: Find and read the CV (ask if unclear).
→ Step 2: Read the job description (from file, or the user will paste it).
→ Step 3: Rewrite the CV content to match the job's requirements and keywords.
→ Step 4: Save the tailored CV as a NEW file (e.g. Lebenslauf_[Firma]_[Datum].md)
           so the original is preserved.
→ Step 5: Open it in the editor. Ask if the user wants a PDF.
→ Step 6 (if yes): convert_to_pdf → tell user the PDF path.

── COVER LETTER / ANSCHREIBEN ─────────────────────────────────────────────────
User: "Schreib ein Anschreiben" / "make a cover letter for [company]"
→ Step 1: Read the job description and the CV.
→ Step 2: Write a professional Anschreiben in Markdown.
          Structure: Ort/Datum, Adresse, Betreff, Anrede, 3-4 Absätze, Grußformel.
          Tone: formal German unless user requests English.
→ Step 3: Save to ~/Bewerbungen/Anschreiben_[Firma]_[Datum].md
→ Step 4: Open in editor with <open_file path="..."/>
→ Step 5: Tell user: "Read it, correct me in chat, I will update the file."
→ After user approves: convert_to_pdf → tell user the PDF path.
→ PDF naming: Anschreiben_[Firma]_[Datum].pdf — ready to attach to application.

── DOCUMENT → PDF ─────────────────────────────────────────────────────────────
User: "Mach ein PDF davon" / "convert to PDF" / "als PDF exportieren"
→ Use the currently open file or ask which file.
→ <tool_call>{"name":"convert_to_pdf","arguments":{"input":"path/to/file.md","output":"path/to/file.pdf"}}</tool_call>
→ If pandoc not installed: offer to install it automatically.
→ Tell user the PDF location.

── READING EMAILS ─────────────────────────────────────────────────────────────
User: "Zeig mir meine Emails von heute" / "read my emails" / "was habe ich für Emails"
→ Check if email is configured:
  <bash>test -f ~/.config/astraeus/email.json && echo "configured" || echo "not configured"</bash>
→ If NOT configured: ask the user for their email provider, address, and password.
  Say: "I need your email credentials to set this up. They will be saved locally in
  ~/.config/astraeus/email.json with permissions 600 (only you can read them)."
  Then: <tool_call>{"name":"setup_email","arguments":{"imap_host":"...","username":"...","password":"..."}}</tool_call>
→ Fetch emails:
  <tool_call>{"name":"read_emails","arguments":{"date":"TODAY","count":20}}</tool_call>
→ For EACH email write a summary: sender, subject, and 2–3 sentence summary of the content.
  Number them. Example:
  "1. Von Max Muster | Betreff: Meeting Donnerstag
     Max fragt ob wir das Team-Meeting von Donnerstag auf Freitag verschieben können..."

── REPLYING TO AN EMAIL ───────────────────────────────────────────────────────
User: "Antworte auf die Email von [person]" / "write a reply to email #3"
→ Read the email content carefully (from the previous read_emails result or fetch it again).
→ Draft a reply that:
   - Matches the user's usual tone (formal/informal based on the original)
   - Addresses all points raised in the original email
   - Is signed with the user's name
→ Save as draft:
  <tool_call>{"name":"draft_email","arguments":{"to":"sender@example.com","subject":"Re: Subject","body":"...","reply_to_message_id":"<msg-id>"}}</tool_call>
→ Show the full draft text in chat.
→ Say: "This is the draft. Tell me if you want changes. I will NOT send it until you say so."
→ NEVER call any send command. Draft only.

── DOWNLOADING FILES / MODEL CARDS / HUGGINGFACE ──────────────────────────────
User: "Lade die model card herunter" / "download model card for [model]" / "lade [url] herunter"
→ Determine the URL. For HuggingFace model cards the README.md is at:
  https://huggingface.co/[author]/[model]/resolve/main/README.md
→ Download it immediately with wget or the download_file tool. Example:
  <bash>wget "https://huggingface.co/mistralai/Mistral-7B-v0.1/resolve/main/README.md" -O ~/Downloads/mistral_model_card.md && echo "Done"</bash>
→ Open the file in the editor: <open_file path="~/Downloads/mistral_model_card.md"/>
→ Tell the user: "Herunterguserden und geöffnet: ~/Downloads/mistral_model_card.md"
→ Do NOT write a script. Do NOT explain how to do it. Just do it.

User: "Lade [datei] von [url] herunter" / "download [url]"
→ <bash>wget "[url]" -O ~/Downloads/[filename] && echo "Done"</bash>
  or: <tool_call>{"name":"download_file","arguments":{"url":"[url]","destination":"~/Downloads/[filename]"}}</tool_call>

── INSTALLING SOFTWARE / GAMES ────────────────────────────────────────────────
User: "Installiere [software]" / "install [game]"
→ Check if it exists: apt-cache search, snap find, or flatpak search.
→ Tell user what you found and which package you will install.
→ Install it.
→ If it is a game/graphical app: offer to launch it with open_application.

── AI TRUST POLICY ────────────────────────────────────────────────────────────
ONLY use local models and Anthropic Claude. No other AI company APIs.
Permitted external calls: Anthropic API only (via call_claude tool).
All other AI services (OpenAI, Google, Meta, Mistral cloud, etc.) are FORBIDDEN.
The call_claude tool enforces this — it rejects non-Claude model names.

── YOUTUBE & VIDEO COMPANION ─────────────────────────────────────────────────
User: "Ich mache gerade ein YouTube Video über [Thema]" / "help me with my video"
→ Ask: title, target audience, video length, tone (funny/educational/professional)
→ Generate: script outline, hook (first 15 seconds), chapter timestamps
→ Generate: YouTube description (SEO-optimised, 250+ words), tags (20+ tags), title variants

User: "Ich habe das Video aufgenommen, schreib die Beschreibung"
→ Ask for: title, topic, key points covered
→ Write: full description, timestamps, tags, CTAs, end screen suggestion

User: "Schau dir mein Thumbnail an" (passes image)
→ Use prepare_for_vision to analyze the thumbnail
→ Feedback: readability, contrast, text size, click-through appeal, suggestions

User: "Ich bin in einem Google Meet / Screen Recording"
→ Use screen_capture to see what's on screen
→ Summarize, suggest talking points, draft follow-up actions

── MEMORY SYSTEM ──────────────────────────────────────────────────────────────
Every folder you work in has astraeus.md (human-readable) + astraeus.json
(keyword-vector index). They are auto-updated every 20 minutes and when you
finish a task. Use them to remember context across conversations.

When you enter a folder, read its memory first:
  <tool_call>{"name":"read_folder_memory","arguments":{"path":"/the/folder"}}</tool_call>

After finishing work in a folder, update its notes:
  <tool_call>{"name":"write_folder_memory","arguments":{"path":"/the/folder","notes":"What this folder is, what was done","activity":"Wrote Anschreiben for BMW"}}</tool_call>

To find documents anywhere on the PC before doing find_file:
  <tool_call>{"name":"search_all_memory","arguments":{"query":"lebenslauf cv bewerbung"}}</tool_call>
  Then open the best-match folders and search within them.

To see all mounted drives and external disks:
  <tool_call>{"name":"list_mounted_drives","arguments":{}}</tool_call>

── GENERAL TASKS ──────────────────────────────────────────────────────────────
- For any task: think step by step, execute completely, report results.
- Always use absolute paths.
- Always use python3 (not python).
- After every tool result: continue working until the task is FULLY done.
- If an error occurs: diagnose the cause and fix it — do not just report it.
- Language: respond in the same language the user uses (Deutsch or English).
- If the user says "korrigiere das" or "change X to Y": update the file immediately."""


class IDEAgent:
    def __init__(self, main_window):
        self.gui = main_window
        self.db_manager = main_window.db_manager
        self._cwd = os.path.dirname(os.path.abspath(__file__))
        self._mcp = None
        self._memory = None
        self._pending_vision: list[dict] = []  # [(mime, base64)] queued for next API call
        self._init_mcp()
        self._init_memory()

    def _init_mcp(self):
        try:
            from mcp_client import MCPClient
            self._mcp = MCPClient(_MCP_SERVER_SCRIPT)
            self._mcp.start()
            print(f"[IDEAgent] MCP ready — {len(self._mcp.list_tools())} tools available")
        except Exception as e:
            print(f"[IDEAgent] MCP unavailable (XML tools still active): {e}")
            self._mcp = None

    def _init_memory(self):
        try:
            from astraeus_memory import FolderMemory
            self._memory = FolderMemory(interval_minutes=20)
            self._memory.start()
            self._memory.set_folder(self._cwd)
            print(f"[IDEAgent] FolderMemory started — watching {self._cwd}")
        except Exception as e:
            print(f"[IDEAgent] FolderMemory unavailable: {e}")
            self._memory = None

    # ------------------------------------------------------------------ #
    #  Explorer                                                            #
    # ------------------------------------------------------------------ #

    def get_explorer_files(self):
        """Return a list of top-level files in the workspace to provide context."""
        workspace_dir = self.gui.path_var.get() or self._cwd
        files = []
        if os.path.isdir(workspace_dir):
            try:
                # Provide top-level files and directories
                for entry in sorted(os.scandir(workspace_dir), key=lambda e: (not e.is_dir(), e.name.lower())):
                    if not entry.name.startswith('.'):
                        if entry.is_file():
                            files.append(entry.path)
                        elif entry.is_dir():
                            files.append(entry.path + "/")
            except PermissionError:
                pass
        return files

    # ------------------------------------------------------------------ #
    #  Editor                                                              #
    # ------------------------------------------------------------------ #

    def get_editor_content(self):
        try:
            return self.gui.editor_text.get('1.0', tk.END)
        except Exception:
            return ''

    def set_editor_content(self, content):
        try:
            self.gui.editor_text.delete('1.0', tk.END)
            self.gui.editor_text.insert('1.0', content)
        except Exception as e:
            print(f"[IDEAgent] set_editor_content error: {e}")

    def get_current_file_path(self):
        return getattr(self.gui, '_current_file_path', None)

    def set_current_file_path(self, path):
        """Set the current file path via the central _set_open_file helper."""
        try:
            self.gui._set_open_file(path)
        except Exception as e:
            print(f"[IDEAgent] set_current_file_path error: {e}")

    def open_file_in_editor(self, path):
        """Open a file in the editor: read it, set as current, display in editor."""
        try:
            content = self.read_file(path)
            if content and not content.startswith("Error"):
                self.gui.root.after(0, lambda: self.set_editor_content(content))
                self.set_current_file_path(path)
                return f"Opened: {path}"
            else:
                return content  # return the error message
        except Exception as e:
            return f"Error opening {path}: {e}"

    def save_current_file(self):
        path = self.get_current_file_path()
        if not path:
            return "No file is currently open in the editor."
        content = self.get_editor_content()
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return f"Saved: {path}"
        except Exception as e:
            return f"Error saving {path}: {e}"

    # ------------------------------------------------------------------ #
    #  File I/O                                                            #
    # ------------------------------------------------------------------ #

    def read_file(self, path):
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                return f.read()
        except Exception as e:
            return f"Error reading {path}: {e}"

    def write_file(self, path, content):
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            _parent = os.path.dirname(os.path.abspath(path))
            try:
                self.gui.root.after(0, lambda p=_parent: self.gui.refresh_tree_node(p))
            except Exception:
                pass
            return f"Written: {path}"
        except Exception as e:
            return f"Error writing {path}: {e}"

    # ------------------------------------------------------------------ #
    #  Bash execution                                                      #
    # ------------------------------------------------------------------ #

    def run_command(self, cmd, timeout=600):
        """
        Run a bash command string, capture stdout+stderr, return the output.
        Updates self._cwd if the command is a bare 'cd <dir>'.
        Echoes the command to the active terminal tab so the user can see it.
        """
        stripped = cmd.strip()

        # Only intercept a bare 'cd <dir>' when it is the single command on one
        # line (no newlines, no &&, no ;).  Multi-line blocks are passed straight
        # to bash so it can handle cd naturally within the subshell.
        lines = [l for l in stripped.splitlines() if l.strip()]
        is_bare_cd = (
            len(lines) == 1
            and lines[0].strip().startswith('cd ')
            and '&&' not in lines[0]
            and ';'  not in lines[0]
        )
        if is_bare_cd:
            new_dir = lines[0].strip()[3:].strip().strip('"').strip("'")
            new_dir = os.path.expanduser(new_dir)
            if not os.path.isabs(new_dir):
                new_dir = os.path.join(self._cwd, new_dir)
            new_dir = os.path.normpath(new_dir)
            if os.path.isdir(new_dir):
                self._cwd = new_dir
                if self._memory:
                    self._memory.set_folder(self._cwd)
                return f"[cwd changed to {self._cwd}]"
            else:
                return f"cd: {new_dir}: No such directory"

        # Replace bare 'python' with 'python3' so scripts run with the correct interpreter
        import re as _re
        stripped = _re.sub(r'\bpython\b(?!3)', 'python3', stripped)

        # Echo the command into the GUI terminal so the user sees it
        self._echo_to_terminal(f"[agent] $ {stripped}\n")

        try:
            result = subprocess.run(
                stripped,
                shell=True,
                cwd=self._cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = result.stdout
            if result.stderr:
                output += result.stderr
            if not output:
                output = f"[exit code {result.returncode}]"
        except subprocess.TimeoutExpired:
            output = f"[command timed out after {timeout}s]"
        except Exception as e:
            output = f"[error running command: {e}]"

        # Echo output to terminal too
        self._echo_to_terminal(output if output.endswith('\n') else output + '\n')
        return output

    def open_terminal_tab(self):
        """Open a new bash tab in the GUI terminal notebook."""
        try:
            self.gui.root.after(0, self.gui._new_terminal_tab)
            return "Opened a new terminal tab."
        except Exception as e:
            return f"Could not open terminal tab: {e}"

    def _echo_to_terminal(self, text):
        """Append text to the active terminal tab (non-blocking, from any thread)."""
        try:
            tw = self.gui.terminal_text
            if tw:
                def _do():
                    try:
                        tw.configure(state='normal')
                        tw.insert(tk.END, text)
                        tw.see(tk.END)
                    except Exception:
                        pass
                self.gui.root.after(0, _do)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    #  Workspace context                                                   #
    # ------------------------------------------------------------------ #

    def get_workspace_context(self):
        current_path = self.get_current_file_path()
        editor_content = self.get_editor_content() if current_path else None
        files = self.get_explorer_files()
        return {
            "explorer_files": files,
            "current_file": current_path,
            "editor_content": editor_content,
            "cwd": self._cwd,
        }

    # ------------------------------------------------------------------ #
    #  Agentic loop helpers                                                #
    # ------------------------------------------------------------------ #

    def _extract_vision_blocks(self, text: str) -> str:
        """
        Pull [VISION_IMAGE:mime]...base64...[/VISION_IMAGE] blocks out of a
        tool result string, queue them for the next API call, and return the
        text with the raw base64 replaced by a short placeholder.
        """
        def _grab(match):
            mime = match.group(1)
            b64 = match.group(2).strip()
            self._pending_vision.append({"mime": mime, "base64": b64})
            idx = len(self._pending_vision)
            return f"[Vision image #{idx} queued — will be sent to model]"
        return _VISION_BLOCK_RE.sub(_grab, text)

    def _build_user_content(self, text: str) -> object:
        """
        Build a message content value. If vision images are pending AND
        the current model is a vision model, return a multimodal list.
        Otherwise return plain text.
        """
        model_name = self.gui.model_var.get()
        if self._pending_vision and _is_vision_model(model_name):
            parts: list[dict] = [{"type": "text", "text": text}]
            for img in self._pending_vision:
                parts.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{img['mime']};base64,{img['base64']}"
                    },
                })
            self._pending_vision.clear()
            return parts
        # Non-vision or no pending images
        self._pending_vision.clear()
        return text

    def _has_tool_calls(self, text: str) -> bool:
        """Return True if the response contains any executable tool tags."""
        return bool(
            re.search(r'<bash>.*?</bash>', text, re.DOTALL) or
            re.search(r'<new_file\s+path="[^"]+">', text) or
            re.search(r'<file_content>', text) or
            re.search(r'<open_file\s+path="[^"]+"\s*/>', text) or
            (self._mcp and re.search(r'<tool_call>', text))
        )

    def _run_tools_collect(self, response: str):
        """
        Execute all tool tags in response.
        Returns (display_text, tool_results_for_feedback).
        display_text has <bash> blocks replaced with their output.
        tool_results_for_feedback is fed back to the model as context.
        """
        tool_results = []

        # Run bash blocks and collect results
        def _run(match):
            cmd = match.group(1).strip()
            output = self.run_command(cmd)
            tool_results.append(f"$ {cmd}\n{output.rstrip()}")
            return f"\n```\n$ {cmd}\n{output.rstrip()}\n```\n"

        text = re.compile(r'<bash>(.*?)</bash>', re.DOTALL).sub(_run, response)

        # Dispatch <tool_call>{...}</tool_call> blocks via MCP
        if self._mcp:
            def _run_mcp(match):
                raw = match.group(1)
                try:
                    call = json.loads(raw)
                except json.JSONDecodeError as e:
                    msg = f"[tool_call parse error: {e}]"
                    tool_results.append(msg)
                    return f"\n```\n{msg}\n```\n"
                name = call.get("name", "")
                mcp_args = call.get("arguments", {})
                output = self._mcp.call_tool(name, mcp_args)
                # Extract vision images from tool output and queue them
                clean_output = self._extract_vision_blocks(output)
                tool_results.append(f"[{name}]\n{clean_output.rstrip()}")
                return f"\n```\n[{name}]\n{clean_output.rstrip()}\n```\n"
            text = re.compile(r'<tool_call>\s*(\{.*?\})\s*</tool_call>', re.DOTALL).sub(_run_mcp, text)

        # Open existing file in editor
        text = self._apply_open_file_blocks(text)
        m = re.search(r'\[Opened in editor: (.+?)\]', text)
        if m:
            tool_results.append(f"Opened file in editor: {m.group(1)}")

        # Apply new_file blocks
        text = self._apply_new_file_blocks(text)
        m = re.search(r'\[Created and opened: (.+?)\]', text)
        if m:
            tool_results.append(f"Created file: {m.group(1)}")

        # Apply file edits
        text = self._apply_file_edits(text)
        m = re.search(r'\[File saved: (.+?)\]', text)
        if m:
            tool_results.append(f"Saved file: {m.group(1)}")

        results_summary = "\n\n".join(tool_results) if tool_results else "(file operation completed)"
        return text, results_summary

    def _append_to_chat(self, text: str, tag: str = 'ai_text'):
        """Thread-safe: append text to the chat display."""
        try:
            def _do():
                try:
                    cd = self.gui.chat_display
                    cd.configure(state='normal')
                    cd.insert(tk.END, text, tag)
                    cd.see(tk.END)
                    cd.configure(state='disabled')
                except Exception:
                    pass
            self.gui.root.after(0, _do)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    #  Message processing — fully autonomous agentic loop                 #
    # ------------------------------------------------------------------ #

    def process_message(self, user_message):
        ctx = self.get_workspace_context()
        files_list = "\n".join(ctx["explorer_files"]) if ctx["explorer_files"] else "(no folder open)"
        current = ctx["current_file"] or "(none)"
        editor = ctx["editor_content"] or "(no file open)"

        # Retrieve relevant memories for this message
        memory_block = ""
        try:
            mb = self.gui.memory_bridge
            memories = mb.retrieve_with_scores(1, user_message, top_n=4)
            if memories:
                lines = []
                for m in memories:
                    if m["score"] > 0:
                        lines.append(f"  [{m['speaker']}] {m['text']}  (score={m['score']:.2f})")
                if lines:
                    memory_block = "\n=== RELEVANT MEMORY ===\n" + "\n".join(lines) + "\n======================\n"
        except Exception:
            pass

        workspace_block = (
            f"\n\n=== WORKSPACE STATE ===\n"
            f"Working directory: {ctx['cwd']}\n"
            f"Explorer files:\n{files_list}\n\n"
            f"Currently open file: {current}\n\n"
            f"File content:\n{editor}\n"
            f"======================\n"
        )
        mcp_block = ""
        if self._mcp:
            tool_lines = [
                "\n── MCP tools ─────────────────────────────────────────────────────────────────",
                "Use <tool_call> for file operations and search (in addition to <bash>):",
                "<tool_call>",
                '{"name": "tool_name", "arguments": {"key": "value"}}',
                "</tool_call>",
                "",
                "Available MCP tools:",
            ]
            for t in self._mcp.list_tools():
                tool_lines.append(f"  - {t['name']}: {t.get('description', '')}")
            mcp_block = "\n".join(tool_lines)

        # Folder memory context (astraeus.md for current working directory)
        folder_memory_block = ""
        if self._memory:
            mem_text = self._memory.get_context_block(self._cwd)
            if mem_text:
                folder_memory_block = (
                    f"\n\n=== FOLDER MEMORY (astraeus.md for {self._cwd}) ===\n"
                    f"{mem_text}\n"
                    f"=================================================\n"
                )

        model_name = self.gui.model_var.get()

        # Per-model persona overlay (AI_Assistant=creative, Devstral=coding, etc.)
        persona_block = _get_persona(model_name)

        # Vision mode note
        vision_block = ""
        if _is_vision_model(model_name):
            vision_block = (
                "\n\n── VISION MODE ACTIVE ────────────────────────────────────────────────────────\n"
                "This model can see images. To analyze any file:\n"
                '  <tool_call>{"name":"prepare_for_vision","arguments":{"path":"/path/to/file"}}</tool_call>\n'
                "For a screenshot of the current screen:\n"
                '  <tool_call>{"name":"screen_capture","arguments":{}}</tool_call>\n'
                "Supported: images, videos, PDFs, 3D files, UE5 assets, SolidWorks, YouTube URLs.\n"
                "After prepare_for_vision returns, the image is automatically attached to your next reply.\n"
            )

        full_system = SYSTEM_PROMPT + persona_block + vision_block + mcp_block + folder_memory_block + workspace_block + memory_block

        history = []
        try:
            history = self.db_manager.chat_history[-12:]
        except Exception:
            pass

        messages = [{"role": "system", "content": full_system}]
        for entry in history:
            messages.append({"role": "user",      "content": entry.get("user", "")})
            messages.append({"role": "assistant", "content": entry.get("assistant", "")})
        messages.append({"role": "user", "content": self._build_user_content(user_message)})

        final_display = ""

        # ── Agentic loop ────────────────────────────────────────────────
        for iteration in range(MAX_AGENT_ITERS):
            response = self.gui._call_model_api_messages(model_name, messages)

            if _is_error_response(response):
                return response

            if not self._has_tool_calls(response):
                # No tool calls — this is the final answer
                final_display = response
                break

            # Execute tools and collect results for feedback
            display_text, tool_results = self._run_tools_collect(response)
            final_display = display_text

            # Stream intermediate step to chat so user sees progress
            self._append_to_chat(display_text + "\n", 'ai_text')

            # --- USER CONFIRMATION: Ask before continuing to next iteration ---
            tool_results_preview = tool_results[:300] + "..." if len(tool_results) > 300 else tool_results
            user_continues = messagebox.askyesno(
                "Agent: Schritt bestätigen",
                f"Schritt {iteration + 1}/{MAX_AGENT_ITERS}\n\n"
                f"Tool-Ergebnis:\n{tool_results_preview}\n\n"
                f"Möchtest du weitermachen?"
            )
            if not user_continues:
                final_display = f"[Abgebrochen nach Schritt {iteration + 1}]"
                break
            # --- END USER CONFIRMATION ---

            # Add the model's reasoning + tool results to the conversation
            messages.append({"role": "assistant", "content": response})
            feedback_text = (
                f"[Tool output — step {iteration + 1}]\n"
                f"{tool_results}\n\n"
                "Continue with the task. When fully done, give your final answer "
                "without any <bash> or <file_content> tags."
            )
            messages.append({
                "role": "user",
                "content": self._build_user_content(feedback_text),
            })
        else:
            # Hit MAX_AGENT_ITERS without a clean finish
            final_display = "[Max steps reached — see terminal for full output.]"
        # ── End agentic loop ────────────────────────────────────────────

        # Persist only clean exchanges — never save error responses
        if not _is_error_response(final_display):
            try:
                self.db_manager.add_message_to_history(user_message, final_display)
            except Exception:
                pass
            try:
                self.gui.memory_bridge.store_exchange(user_message, final_display)
            except Exception:
                pass
            # Log this task to the folder memory
            if self._memory:
                try:
                    short_task = user_message[:120].replace("\n", " ")
                    self._memory.log_activity(self._cwd, f"Task: {short_task}")
                except Exception:
                    pass

        return final_display

    # ------------------------------------------------------------------ #
    #  Response parsing (used by _run_tools_collect)                      #
    # ------------------------------------------------------------------ #

    def _apply_actions(self, response):
        """Process all tool tags in model response."""
        response = self._apply_bash_blocks(response)
        response = self._apply_open_file_blocks(response)
        response = self._apply_new_file_blocks(response)
        response = self._apply_file_edits(response)
        return response

    def _apply_bash_blocks(self, response):
        """Find all <bash>…</bash> blocks, run them, replace with output."""
        pattern = re.compile(r'<bash>(.*?)</bash>', re.DOTALL)

        def _run(match):
            cmd = match.group(1).strip()
            output = self.run_command(cmd)
            return f"\n```\n$ {cmd}\n{output.rstrip()}\n```\n"

        return pattern.sub(_run, response)

    def _apply_open_file_blocks(self, response):
        """Find <open_file path="..."/> tags and open the file in the editor."""
        pattern = re.compile(r'<open_file\s+path="([^"]+)"\s*/>', re.DOTALL)

        def _open(match):
            raw_path = match.group(1).strip()
            file_path = raw_path if os.path.isabs(raw_path) else os.path.join(self._cwd, raw_path)
            file_path = os.path.normpath(file_path)
            if not os.path.isfile(file_path):
                return f"\n[open_file: not found: {file_path}]\n"
            # Open in a new workspace tab (or switch to existing) on the main thread
            self.gui.root.after(0, lambda p=file_path: self.gui._open_in_editor_tab(p))
            # Refresh explorer
            try:
                self.gui.root.after(0, lambda p=os.path.dirname(file_path):
                                    self.gui.refresh_tree_node(p))
            except Exception:
                pass
            return f"\n[Opened in editor: {file_path}]\n"

        return pattern.sub(_open, response)

    def _apply_new_file_blocks(self, response):
        """Find <new_file path="...">content</new_file>, create file and open in editor."""
        pattern = re.compile(r'<new_file\s+path="([^"]+)">(.*?)</new_file>', re.DOTALL)
        match = pattern.search(response)
        if not match:
            return response

        file_path = match.group(1).strip()
        new_content = match.group(2).lstrip('\n')

        # If path is rusertive, prepend the current working directory
        if not os.path.isabs(file_path):
            file_path = os.path.join(self._cwd, file_path)

        # Ensure parent directory exists
        parent_dir = os.path.dirname(file_path)
        if parent_dir and not os.path.exists(parent_dir):
            try:
                os.makedirs(parent_dir, exist_ok=True)
            except Exception as e:
                return pattern.sub('', response).rstrip() + f"\n\n[Error creating directory {parent_dir}: {e}]"

        # Write the file
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
        except Exception as e:
            return pattern.sub('', response).rstrip() + f"\n\n[Error writing file {file_path}: {e}]"

        # Open the file in the editor and refresh the explorer
        try:
            self.gui.root.after(0, lambda: self.set_editor_content(new_content))
            self.set_current_file_path(file_path)
        except Exception as e:
            print(f"[IDEAgent] Error opening file in editor: {e}")

        # Refresh the explorer so the new file appears immediately
        _parent = os.path.dirname(file_path)
        try:
            self.gui.root.after(0, lambda p=_parent: self.gui.refresh_tree_node(p))
        except Exception:
            pass

        return pattern.sub('', response).rstrip() + f"\n\n[Created and opened: {file_path}]"

    def _apply_file_edits(self, response):
        """Find <file_content>…</file_content>, apply to editor and save."""
        pattern = re.compile(r'<file_content>(.*?)</file_content>', re.DOTALL)
        match = pattern.search(response)
        if not match:
            return response

        new_content = match.group(1).lstrip('\n')
        path = self.get_current_file_path()

        try:
            self.gui.root.after(0, lambda: self.set_editor_content(new_content))
        except Exception:
            pass

        if path:
            try:
                # backup before overwriting
                try:
                    self.gui._make_timestamped_backup(path)
                except Exception:
                    pass
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                notice = f"\n\n[File saved: {path}]"
            except Exception as e:
                notice = f"\n\n[Error saving file: {e}]"
        else:
            notice = "\n\n[Content applied to editor — no file path to save to. Use <new_file> to create a new file.]"

        return pattern.sub('', response).rstrip() + notice
