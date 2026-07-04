# ==========================================
# Copyright (c) 2026 Gabriela Berger AI Oberland
# All Rights Reserved.
# This code is subject to the custom NON-COMMERCIAL 
# & ANTI-CORPORATE LICENSE (Maximum 20 PCs) found in the LICENSE file.
# ==========================================
"""mcp_server.py — Astraeus IDE full-autonomy MCP server (Linux).

No workspace sandbox. Full filesystem and system access.
Set WORKSPACE_ROOT env var only if you want to restrict file paths.
"""
import asyncio
import logging
import os
import re
import shutil
import subprocess
import signal
import sys
from pathlib import Path
from typing import Optional
import glob

# New imports for advanced tools
import requests
from bs4 import BeautifulSoup
from googlesearch import search as google_search

# Allow importing astraeus_memory.py and astraeus_vision.py from the same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server import NotificationOptions, Server
import mcp.server.stdio

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

SERVER_NAME = "astraeus-mcp"
SERVER_VERSION = "2.0.0"

# Optional workspace boundary (set WORKSPACE_ROOT env var to enable)
_WORKSPACE_ROOT = os.environ.get("WORKSPACE_ROOT")
_workspace = Path(_WORKSPACE_ROOT).resolve() if _WORKSPACE_ROOT else None

# Tracks background processes started via run_background
_bg_procs: dict[int, dict] = {}

_DEFAULT_IGNORE = {".git", "__pycache__", "node_modules", ".venv", "venv",
                   ".mypy_cache", "dist", "build"}

server = Server(SERVER_NAME)


def _resolve(path: str) -> Path:
    """Resolve a path. Enforces workspace boundary only when WORKSPACE_ROOT is set."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        base = _workspace if _workspace else Path.home()
        p = base / p
    p = p.resolve()
    if _workspace:
        try:
            p.relative_to(_workspace)
        except ValueError:
            raise PermissionError(f"Path {p} is outside workspace {_workspace}")
    return p


# ── Tool definitions ──────────────────────────────────────────────────────────

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [

        # ── Advanced Tools (Web, UI, Editing) ────────────────────────────
        types.Tool(
            name="replace_text",
            description="Replaces exact literal text within a file without reading/writing the whole file. Preferred for surgical edits.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_string": {"type": "string", "description": "Exact text to remove"},
                    "new_string": {"type": "string", "description": "Exact text to insert"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        ),
        types.Tool(
            name="web_fetch",
            description="Fetches and extracts readable text from a webpage (URL).",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to fetch"},
                },
                "required": ["url"],
            },
        ),
        types.Tool(
            name="web_search",
            description="Performs a Google Search and returns a list of result URLs and summaries.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                    "num_results": {"type": "integer", "description": "Number of results (default 5)"},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="pyautogui_control",
            description="Controls the mouse and keyboard on the host UI.",
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["click", "type", "press", "move", "hotkey"]},
                    "text": {"type": "string", "description": "Text for 'type' action"},
                    "key": {"type": "string", "description": "Key for 'press' or comma-separated keys for 'hotkey'"},
                    "x": {"type": "integer", "description": "X coordinate for 'click' or 'move'"},
                    "y": {"type": "integer", "description": "Y coordinate for 'click' or 'move'"},
                },
                "required": ["action"],
            },
        ),

        # ── File I/O ──────────────────────────────────────────────────────
        types.Tool(
            name="read_file",
            description="Read file contents. offset and limit select a line range.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "offset": {"type": "integer", "description": "Start line (1-indexed, default 1)"},
                    "limit": {"type": "integer", "description": "Max lines (default 500)"},
                },
                "required": ["path"],
            },
        ),
        types.Tool(
            name="write_file",
            description="Write (overwrite) a file. Creates parent directories automatically.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        ),
        types.Tool(
            name="append_file",
            description="Append text to a file. Creates the file if it does not exist.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        ),
        types.Tool(
            name="copy_file",
            description="Copy a file or directory to a new location.",
            inputSchema={
                "type": "object",
                "properties": {
                    "src": {"type": "string"},
                    "dst": {"type": "string"},
                },
                "required": ["src", "dst"],
            },
        ),
        types.Tool(
            name="move_file",
            description="Move or rename a file or directory.",
            inputSchema={
                "type": "object",
                "properties": {
                    "src": {"type": "string"},
                    "dst": {"type": "string"},
                },
                "required": ["src", "dst"],
            },
        ),
        types.Tool(
            name="delete_file",
            description="Delete a file or directory (recursive for directories). Irreversible — confirm with user first.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
            },
        ),
        types.Tool(
            name="make_dir",
            description="Create a directory and all parent directories (mkdir -p).",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
            },
        ),

        # ── Directory navigation ───────────────────────────────────────────
        types.Tool(
            name="list_dir",
            description="List files and directories at a path (top level).",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Default: home directory"},
                },
                "required": [],
            },
        ),
        types.Tool(
            name="directory_tree",
            description="Recursive tree view of a directory. Skips common noise folders.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Default: home directory"},
                    "max_depth": {"type": "integer", "description": "Default 3"},
                },
                "required": [],
            },
        ),
        types.Tool(
            name="search",
            description="Search file contents for a pattern (grep-like). Supports regex.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string", "description": "Root directory, default: home"},
                    "regex": {"type": "boolean", "description": "Use regex (default false)"},
                    "max_results": {"type": "integer", "description": "Default 200"},
                },
                "required": ["pattern"],
            },
        ),
        types.Tool(
            name="glob_search",
            description="Find files by glob pattern, e.g. '**/*.py'.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string", "description": "Root directory, default: home"},
                },
                "required": ["pattern"],
            },
        ),
        types.Tool(
            name="find_file",
            description="Find files/directories by name anywhere on the filesystem.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Filename or pattern (e.g. '*.conf')"},
                    "path": {"type": "string", "description": "Start path, default: /"},
                    "type": {"type": "string", "description": "'f' for files, 'd' for dirs, default: both"},
                    "max_results": {"type": "integer", "description": "Default 50"},
                },
                "required": ["name"],
            },
        ),

        # ── Shell ──────────────────────────────────────────────────────────
        types.Tool(
            name="bash",
            description=(
                "Run any shell command with full system access. "
                "For long operations (installs, compiles) set a higher timeout. "
                "Always tell the user what you are about to run before calling this."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "cwd": {"type": "string", "description": "Working directory (default: home)"},
                    "timeout": {"type": "integer", "description": "Seconds (default 60, max 1800)"},
                },
                "required": ["command"],
            },
        ),

        # ── System info ────────────────────────────────────────────────────
        types.Tool(
            name="system_info",
            description="Show system overview: OS, hostname, CPU, RAM, disk, uptime, kernel.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="list_processes",
            description="List running processes. Optionally filter by name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filter": {"type": "string", "description": "Filter by process name (optional)"},
                    "top": {"type": "integer", "description": "Show only top N by CPU usage"},
                },
                "required": [],
            },
        ),
        types.Tool(
            name="kill_process",
            description="Kill a process by PID or name. Confirm with user before calling.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pid": {"type": "integer", "description": "Process ID"},
                    "name": {"type": "string", "description": "Process name (kills all matching)"},
                    "signal": {"type": "string", "description": "TERM (default) or KILL"},
                },
                "required": [],
            },
        ),

        # ── Package management ─────────────────────────────────────────────
        types.Tool(
            name="package_manager",
            description=(
                "Manage software packages. Supports apt (system), pip/pip3 (Python), "
                "snap, flatpak. Always tell the user what will be installed/removed first."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "install | remove | update | upgrade | search | list | show | autoremove",
                    },
                    "packages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Package names (empty for update/upgrade/list)",
                    },
                    "manager": {
                        "type": "string",
                        "description": "apt | pip | pip3 | snap | flatpak (default: apt)",
                    },
                },
                "required": ["action"],
            },
        ),

        # ── Downloads & archives ───────────────────────────────────────────
        types.Tool(
            name="download_file",
            description="Download a file from a URL to a local path using wget.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "destination": {"type": "string", "description": "Save path (default: ~/Downloads/)"},
                    "timeout": {"type": "integer", "description": "Seconds (default 300)"},
                },
                "required": ["url"],
            },
        ),
        types.Tool(
            name="extract_archive",
            description="Extract a zip, tar.gz, tar.bz2, tar.xz, 7z, or rar archive.",
            inputSchema={
                "type": "object",
                "properties": {
                    "archive": {"type": "string", "description": "Path to archive file"},
                    "destination": {"type": "string", "description": "Extract to this dir (default: same dir as archive)"},
                },
                "required": ["archive"],
            },
        ),
        types.Tool(
            name="compress_files",
            description="Create a zip or tar.gz archive from files or a directory.",
            inputSchema={
                "type": "object",
                "properties": {
                    "sources": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Files/directories to include",
                    },
                    "output": {"type": "string", "description": "Output archive path (.zip or .tar.gz)"},
                },
                "required": ["sources", "output"],
            },
        ),

        # ── Services ───────────────────────────────────────────────────────
        types.Tool(
            name="service_control",
            description="Manage systemd services (start, stop, restart, status, enable, disable, list).",
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "start | stop | restart | status | enable | disable | list"},
                    "service": {"type": "string", "description": "Service name (not needed for list)"},
                },
                "required": ["action"],
            },
        ),

        # ── Background processes ───────────────────────────────────────────
        types.Tool(
            name="run_background",
            description="Start a command as a detached background process. Returns PID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "cwd": {"type": "string", "description": "Working directory (default: home)"},
                    "label": {"type": "string", "description": "Human-readable label for tracking"},
                },
                "required": ["command"],
            },
        ),
        types.Tool(
            name="list_background",
            description="List background processes started in this session.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),

        # ── Desktop ────────────────────────────────────────────────────────
        types.Tool(
            name="open_application",
            description="Open a file, URL, or launch an application using xdg-open.",
            inputSchema={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "File path, URL, or application name"},
                },
                "required": ["target"],
            },
        ),
        types.Tool(
            name="desktop_notify",
            description="Send a desktop notification popup via notify-send.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "message": {"type": "string"},
                    "urgency": {"type": "string", "description": "low | normal | critical (default: normal)"},
                },
                "required": ["title", "message"],
            },
        ),

        # ── Memory ────────────────────────────────────────────────────────
        types.Tool(
            name="list_mounted_drives",
            description=(
                "List all mounted filesystems and external drives on the Linux PC. "
                "Shows mount point, size, used/free space, and filesystem type."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="read_folder_memory",
            description=(
                "Read the astraeus.md and astraeus.json memory files for a folder. "
                "Returns the human-readable notes and the keyword-vector metadata. "
                "Call this whenever you enter a folder to get instant context."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Folder path"},
                },
                "required": ["path"],
            },
        ),
        types.Tool(
            name="write_folder_memory",
            description=(
                "Scan a folder and write/update its astraeus.md and astraeus.json. "
                "Optionally add AI-written notes and log an activity entry. "
                "Call after finishing work in a folder."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Folder to update"},
                    "notes": {"type": "string", "description": "AI notes about this folder (what it is, what was done)"},
                    "activity": {"type": "string", "description": "One-line activity to log (e.g. 'Tailored CV for Siemens job')"},
                },
                "required": ["path"],
            },
        ),
        types.Tool(
            name="search_all_memory",
            description=(
                "Search all astraeus.json files on the filesystem and rank folders "
                "by keyword-vector similarity to the query. "
                "Use this to find where a document/project is before scanning with find_file."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language query, e.g. 'lebenslauf cv bewerbung'"},
                    "start_path": {"type": "string", "description": "Root to search from (default: /)"},
                },
                "required": ["query"],
            },
        ),

        # ── Documents & PDF ────────────────────────────────────────────────
        types.Tool(
            name="convert_to_pdf",
            description=(
                "Convert a document to PDF. Supports Markdown (.md), DOCX, ODT, HTML. "
                "Uses pandoc (preferred) or LibreOffice as fallback. "
                "For Markdown CVs/cover letters use this to produce a print-ready PDF."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "input": {"type": "string", "description": "Source file path"},
                    "output": {"type": "string", "description": "Output PDF path (default: same name, .pdf extension)"},
                    "paper": {"type": "string", "description": "Paper size: a4 (default) or letter"},
                    "margin": {"type": "string", "description": "Page margin e.g. '2cm' (default '2.5cm')"},
                    "font_size": {"type": "string", "description": "Font size e.g. '11pt' (default '11pt')"},
                },
                "required": ["input"],
            },
        ),

        # ── Email ──────────────────────────────────────────────────────────
        types.Tool(
            name="setup_email",
            description=(
                "Save email server credentials to ~/.config/astraeus/email.json. "
                "Call this once before using read_emails or draft_email. "
                "Permissions are set to 600 (user-only). "
                "Common IMAP hosts: Gmail=imap.gmail.com:993, Outlook=outlook.office365.com:993, "
                "GMX=imap.gmx.net:993, web.de=imap.web.de:993."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "imap_host": {"type": "string", "description": "IMAP server hostname"},
                    "imap_port": {"type": "integer", "description": "IMAP port (default 993)"},
                    "username": {"type": "string", "description": "Email address"},
                    "password": {"type": "string", "description": "Email password or app password"},
                    "smtp_host": {"type": "string", "description": "SMTP server (optional, auto-guessed from IMAP)"},
                    "smtp_port": {"type": "integer", "description": "SMTP port (default 587)"},
                    "display_name": {"type": "string", "description": "Your name shown in sent emails"},
                },
                "required": ["imap_host", "username", "password"],
            },
        ),
        types.Tool(
            name="read_emails",
            description=(
                "Fetch emails from your inbox using saved credentials. "
                "Call setup_email first if not yet configured. "
                "Returns full headers + body for each email so the AI can summarize or reply."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "description": "Max emails to fetch (default 10)"},
                    "folder": {"type": "string", "description": "Mailbox folder (default INBOX)"},
                    "date": {"type": "string", "description": "Filter: TODAY, YESTERDAY, or date string like '01-Jan-2025'"},
                    "unread_only": {"type": "boolean", "description": "Only fetch unread emails (default false)"},
                },
                "required": [],
            },
        ),
        types.Tool(
            name="draft_email",
            description=(
                "Save a composed email to a .eml draft file. Does NOT send it. "
                "Always use this instead of any send command. "
                "After saving, show the user the file and ask them to review before sending manually."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Email body text"},
                    "reply_to_message_id": {"type": "string", "description": "Message-ID of email being replied to (for threading)"},
                    "path": {"type": "string", "description": "Where to save the draft (default: ~/Drafts/)"},
                },
                "required": ["to", "subject", "body"],
            },
        ),

        # ── Schedule ───────────────────────────────────────────────────────
        types.Tool(
            name="schedule_status",
            description="Show the current daily schedule: shutdown time, wakeup time, enabled state.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="schedule_set",
            description=(
                "Change the daily shutdown and/or wakeup times. "
                "Times are in HH:MM format, Berlin timezone (CEST in summer). "
                "Example: shutdown 00:00, wakeup 08:00."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "shutdown_time": {"type": "string", "description": "HH:MM — time to shut down (default 00:00)"},
                    "wakeup_time":   {"type": "string", "description": "HH:MM — time to wake up (default 08:00)"},
                    "enabled":       {"type": "boolean", "description": "Enable or disable the schedule"},
                    "language":      {"type": "string", "description": "Briefing language: 'Deutsch', 'English', or 'auto'"},
                },
                "required": [],
            },
        ),

        # ── Vision ─────────────────────────────────────────────────────────
        types.Tool(
            name="prepare_for_vision",
            description=(
                "Convert ANY file to a base64 image so a vision model can see it. "
                "Supports: images (jpg/png/gif/bmp/webp/svg/tiff), "
                "videos (mp4/avi/mkv/mov — extracts a frame via ffmpeg), "
                "PDFs (converts a page), "
                "3D files (stl/obj/fbx/blend — renders with Blender if installed), "
                "SolidWorks files (sldprt/sldasm/slddrw — FreeCAD if installed), "
                "UE5 assets (uasset/umap — extracts embedded thumbnail), "
                "Office docs (docx/pptx/odt — LibreOffice), "
                "YouTube / streaming URLs (yt-dlp + ffmpeg). "
                "Returns a VISION_IMAGE block that the IDE attaches to the model call."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path or streaming URL (YouTube, etc.)"},
                    "timestamp": {"type": "number", "description": "For video: frame at this second (default 5.0)"},
                    "page": {"type": "integer", "description": "For PDF: page number (default 1)"},
                },
                "required": ["path"],
            },
        ),
        types.Tool(
            name="screen_capture",
            description=(
                "Capture a screenshot of the current screen or a specific window. "
                "Returns a VISION_IMAGE block. Use when the user says 'look at my screen', "
                "'see what's on screen', or when working alongside a video call / game / browser."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "region": {"type": "string", "description": "Capture region as 'x,y,width,height' (optional)"},
                    "window_title": {"type": "string", "description": "Capture a specific window by title (optional)"},
                },
                "required": [],
            },
        ),
        types.Tool(
            name="call_claude",
            description=(
                "Escalate to Claude (Anthropic cloud API) when local models cannot handle the task. "
                "Use for: complex reasoning, vision analysis that needs accuracy, "
                "repairing broken code, long-context tasks. "
                "Requires ANTHROPIC_API_KEY in environment or ~/.config/astraeus/claude_api.json. "
                "Can include an image (base64) for vision tasks."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "The task or question"},
                    "context": {"type": "string", "description": "Supporting context (code, file content, conversation)"},
                    "model": {
                        "type": "string",
                        "description": "claude-opus-4-7 | claude-sonnet-4-6 | claude-haiku-4-5 (default: claude-sonnet-4-6)",
                    },
                    "image_base64": {"type": "string", "description": "Base64 image for vision tasks (optional)"},
                    "image_mime": {"type": "string", "description": "image/jpeg or image/png (default: image/jpeg)"},
                    "max_tokens": {"type": "integer", "description": "Max response tokens (default 4096)"},
                },
                "required": ["prompt"],
            },
        ),
    ]


# ── Tool implementations ──────────────────────────────────────────────────────

@server.call_tool()
async def handle_call_tool(name: str, arguments: Optional[dict]) -> list[types.TextContent]:
    args = arguments or {}

    def ok(text: str):
        return [types.TextContent(type="text", text=text)]

    def err(text: str):
        return [types.TextContent(type="text", text=f"Error: {text}")]

    try:

        if name == "replace_text":
            path = args.get("path")
            old_str = args.get("old_string")
            new_str = args.get("new_string")
            if not all([path, old_str, new_str]):
                return err("path, old_string, and new_string are required")
            p = _resolve(path)
            if not p.is_file():
                return err(f"not a file: {path}")
            content = p.read_text(encoding="utf-8")
            if old_str not in content:
                return err(f"old_string not found in {path}")
            if content.count(old_str) > 1:
                return err("old_string found multiple times. Make it more specific.")
            new_content = content.replace(old_str, new_str, 1)
            p.write_text(new_content, encoding="utf-8")
            return ok(f"Successfully replaced text in {path}")

        elif name == "web_fetch":
            url = args.get("url")
            if not url:
                return err("url is required")
            try:
                headers = {'User-Agent': 'Mozilla/5.0'}
                resp = requests.get(url, headers=headers, timeout=15)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")
                # Remove scripts and styles
                for script in soup(["script", "style"]):
                    script.extract()
                text = soup.get_text(separator='\\n')
                lines = (line.strip() for line in text.splitlines())
                chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                text = '\\n'.join(chunk for chunk in chunks if chunk)
                # Limit to first ~10000 characters to avoid huge payloads
                return ok(text[:10000] + ("..." if len(text) > 10000 else ""))
            except Exception as e:
                return err(f"Failed to fetch url: {e}")

        elif name == "web_search":
            query = args.get("query")
            if not query:
                return err("query is required")
            num = args.get("num_results", 5)
            try:
                results = []
                for j in google_search(query, num=num, stop=num, pause=2):
                    results.append(j)
                return ok("Google Search Results:\\n" + "\\n".join(results))
            except Exception as e:
                return err(f"Failed to search: {e}")

        elif name == "pyautogui_control":
            action = args.get("action")
            if not action:
                return err("action is required")
            try:
                import pyautogui
                # Set a fail-safe pause
                pyautogui.PAUSE = 0.5
                if action == "click":
                    x, y = args.get("x"), args.get("y")
                    if x is not None and y is not None:
                        pyautogui.click(x, y)
                        return ok(f"Clicked at ({x}, {y})")
                    else:
                        pyautogui.click()
                        return ok("Clicked at current mouse position")
                elif action == "type":
                    text = args.get("text")
                    if not text:
                        return err("text is required for 'type' action")
                    pyautogui.write(text, interval=0.01)
                    return ok(f"Typed text: {text}")
                elif action == "press":
                    key = args.get("key")
                    if not key:
                        return err("key is required for 'press' action")
                    pyautogui.press(key)
                    return ok(f"Pressed key: {key}")
                elif action == "hotkey":
                    keys_str = args.get("key")
                    if not keys_str:
                        return err("key string (comma separated) is required for 'hotkey'")
                    keys = [k.strip() for k in keys_str.split(',')]
                    pyautogui.hotkey(*keys)
                    return ok(f"Pressed hotkey: {keys}")
                elif action == "move":
                    x, y = args.get("x"), args.get("y")
                    if x is not None and y is not None:
                        pyautogui.moveTo(x, y, duration=0.2)
                        return ok(f"Moved mouse to ({x}, {y})")
                    else:
                        return err("x and y are required for 'move' action")
                else:
                    return err(f"Unknown action: {action}")
            except Exception as e:
                return err(f"PyAutoGUI error: {e}")

        elif name == "read_file":
            path = args.get("path")
            if not path:
                return err("path is required")
            p = _resolve(path)
            if not p.exists():
                return err(f"not found: {path}")
            if not p.is_file():
                return err(f"not a file: {path}")
            offset = max(1, args.get("offset", 1))
            limit = args.get("limit", 500)
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            total = len(lines)
            start = offset - 1
            end = min(total, start + limit)
            body = "\n".join(f"{i+1}\t{l}" for i, l in enumerate(lines[start:end], start=start))
            return ok(f"[{p}] lines {start+1}-{end} of {total}\n{body}")

        elif name == "write_file":
            path, content = args.get("path"), args.get("content")
            if not path or content is None:
                return err("path and content are required")
            p = _resolve(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return ok(f"Written {len(content.splitlines())} lines to {p}")

        elif name == "append_file":
            path, content = args.get("path"), args.get("content")
            if not path or content is None:
                return err("path and content are required")
            p = _resolve(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(content)
            return ok(f"Appended to {p}")

        elif name == "copy_file":
            src, dst = args.get("src"), args.get("dst")
            if not src or not dst:
                return err("src and dst are required")
            s, d = _resolve(src), _resolve(dst)
            if not s.exists():
                return err(f"source not found: {src}")
            d.parent.mkdir(parents=True, exist_ok=True)
            if s.is_dir():
                shutil.copytree(s, d, dirs_exist_ok=True)
            else:
                shutil.copy2(s, d)
            return ok(f"Copied {s} -> {d}")

        elif name == "move_file":
            src, dst = args.get("src"), args.get("dst")
            if not src or not dst:
                return err("src and dst are required")
            s, d = _resolve(src), _resolve(dst)
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(s), str(d))
            return ok(f"Moved {s} -> {d}")

        elif name == "delete_file":
            path = args.get("path")
            if not path:
                return err("path is required")
            p = _resolve(path)
            if not p.exists():
                return err(f"not found: {path}")
            if p.is_file():
                p.unlink()
            else:
                shutil.rmtree(p)
            return ok(f"Deleted {p}")

        elif name == "make_dir":
            path = args.get("path")
            if not path:
                return err("path is required")
            p = _resolve(path)
            p.mkdir(parents=True, exist_ok=True)
            return ok(f"Created {p}")

        elif name == "list_dir":
            path = args.get("path") or str(Path.home())
            p = _resolve(path)
            if not p.is_dir():
                return err(f"not a directory: {path}")
            items = []
            for item in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                tag = "[DIR] " if item.is_dir() else "[FILE]"
                size = ""
                if item.is_file():
                    try:
                        size = f"  {item.stat().st_size:,} B"
                    except Exception:
                        pass
                items.append(f"{tag} {item.name}{size}")
            return ok("\n".join(items) if items else "(empty)")

        elif name == "directory_tree":
            path = args.get("path") or str(Path.home())
            max_depth = args.get("max_depth", 3)
            p = _resolve(path)
            if not p.is_dir():
                return err(f"not a directory: {path}")

            def tree(d, prefix="", depth=0):
                if depth > max_depth:
                    return []
                try:
                    children = sorted(Path(d).iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
                    children = [c for c in children if c.name not in _DEFAULT_IGNORE]
                except PermissionError:
                    return [f"{prefix}[Permission Denied]"]
                lines = []
                for i, child in enumerate(children):
                    last = i == len(children) - 1
                    lines.append(f"{prefix}{'└── ' if last else '├── '}{child.name}")
                    if child.is_dir():
                        lines.extend(tree(child, prefix + ("    " if last else "│   "), depth + 1))
                return lines

            return ok("\n".join([str(p)] + tree(p)))

        elif name == "search":
            pattern = args.get("pattern")
            if not pattern:
                return err("pattern is required")
            base = _resolve(args.get("path") or str(Path.home()))
            max_r = args.get("max_results", 200)
            use_re = args.get("regex", False)
            if use_re:
                try:
                    rx = re.compile(pattern)
                    mfn = lambda l: rx.search(l) is not None
                except re.error as e:
                    return err(f"bad regex: {e}")
            else:
                mfn = lambda l: pattern in l
            hits = []
            truncated = False
            for cur, dirs, files in os.walk(base):
                dirs[:] = [d for d in dirs if d not in _DEFAULT_IGNORE]
                for fn in files:
                    fp = Path(cur) / fn
                    try:
                        with fp.open("r", encoding="utf-8", errors="replace") as f:
                            for i, line in enumerate(f, 1):
                                if mfn(line):
                                    hits.append(f"{fp}:{i}: {line.rstrip()[:200]}")
                                    if len(hits) >= max_r:
                                        truncated = True
                                        break
                        if truncated:
                            break
                    except Exception:
                        continue
                if truncated:
                    break
            if not hits:
                return ok("No matches found.")
            out = "\n".join(hits)
            if truncated:
                out += f"\n[truncated at {max_r} results]"
            return ok(out)

        elif name == "glob_search":
            pattern = args.get("pattern")
            if not pattern:
                return err("pattern is required")
            base = args.get("path") or str(Path.home())
            matches = glob.glob(os.path.join(base, pattern), recursive=True)
            if not matches:
                return ok("No matches.")
            return ok("\n".join(sorted(matches)))

        elif name == "find_file":
            name_pat = args.get("name")
            if not name_pat:
                return err("name is required")
            start = args.get("path", "/")
            ftype = args.get("type", "")
            max_r = args.get("max_results", 50)
            type_flag = f"-type {ftype} " if ftype in ("f", "d") else ""
            cmd = f'find {start} {type_flag}-name "{name_pat}" 2>/dev/null | head -n {max_r}'
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            out = r.stdout.strip()
            return ok(out if out else "Nothing found.")

        elif name == "bash":
            command = args.get("command")
            if not command:
                return err("command is required")
            cwd = args.get("cwd") or str(Path.home())
            timeout = min(int(args.get("timeout", 60)), 1800)
            r = subprocess.run(
                command, shell=True, capture_output=True,
                text=True, timeout=timeout, cwd=cwd,
            )
            out = r.stdout.rstrip()
            if r.stderr.strip():
                out += f"\nSTDERR:\n{r.stderr.rstrip()}"
            out += f"\nExit: {r.returncode}"
            return ok(out)

        elif name == "system_info":
            cmds = {
                "Hostname": "hostname",
                "OS": "cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"'",
                "Kernel": "uname -r",
                "Uptime": "uptime -p",
                "CPU": "lscpu 2>/dev/null | grep 'Model name' | cut -d: -f2 | xargs",
                "CPU cores": "nproc",
                "RAM total": "free -h | awk '/^Mem:/{print $2}'",
                "RAM used": "free -h | awk '/^Mem:/{print $3}'",
                "Disk": "df -h --total 2>/dev/null | tail -1 | awk '{print $2\" total, \"$3\" used, \"$4\" free\"}'",
                "GPU": "lspci 2>/dev/null | grep -i 'vga\\|3d\\|display' | head -3",
                "User": "whoami",
                "Shell": "echo $SHELL",
            }
            lines = []
            for label, cmd in cmds.items():
                r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
                val = r.stdout.strip() or "(unknown)"
                lines.append(f"{label:12}: {val}")
            return ok("\n".join(lines))

        elif name == "list_processes":
            filt = args.get("filter", "")
            top_n = args.get("top")
            if filt:
                cmd = f"ps aux | head -1; ps aux | grep -i '{filt}' | grep -v grep"
            else:
                cmd = "ps aux --sort=-%cpu"
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            lines = r.stdout.strip().splitlines()
            if top_n:
                lines = lines[:int(top_n) + 1]
            return ok("\n".join(lines) if lines else "No processes found.")

        elif name == "kill_process":
            pid = args.get("pid")
            pname = args.get("name")
            sig = args.get("signal", "TERM").upper()
            sig_flag = f"-{sig}"
            if pid:
                r = subprocess.run(f"kill {sig_flag} {pid}", shell=True, capture_output=True, text=True)
                return ok(f"Sent {sig} to PID {pid}. {r.stderr.strip()}")
            elif pname:
                r = subprocess.run(f"pkill {sig_flag} -f '{pname}'", shell=True, capture_output=True, text=True)
                return ok(f"Sent {sig} to processes matching '{pname}'. Exit: {r.returncode}")
            else:
                return err("pid or name is required")

        elif name == "package_manager":
            action = args.get("action", "").lower()
            packages = args.get("packages") or []
            mgr = args.get("manager", "apt").lower()
            pkgs = " ".join(packages)
            env = os.environ.copy()

            if mgr == "apt":
                env["DEBIAN_FRONTEND"] = "noninteractive"
                cmds = {
                    "install": f"sudo apt-get install -y {pkgs}",
                    "remove": f"sudo apt-get remove -y {pkgs}",
                    "autoremove": "sudo apt-get autoremove -y",
                    "update": "sudo apt-get update",
                    "upgrade": "sudo apt-get upgrade -y",
                    "search": f"apt-cache search {pkgs}",
                    "show": f"apt-cache show {pkgs}",
                    "list": "apt list --installed 2>/dev/null",
                }
            elif mgr in ("pip", "pip3"):
                cmds = {
                    "install": f"{mgr} install {pkgs}",
                    "remove": f"{mgr} uninstall -y {pkgs}",
                    "list": f"{mgr} list",
                    "show": f"{mgr} show {pkgs}",
                    "search": f"{mgr} index versions {pkgs} 2>/dev/null || echo 'Use pip install to check'",
                    "update": f"{mgr} install --upgrade {pkgs}",
                    "upgrade": f"{mgr} list --outdated",
                }
            elif mgr == "snap":
                cmds = {
                    "install": f"sudo snap install {pkgs}",
                    "remove": f"sudo snap remove {pkgs}",
                    "list": "snap list",
                    "search": f"snap find {pkgs}",
                    "show": f"snap info {pkgs}",
                    "update": f"sudo snap refresh {pkgs}",
                    "upgrade": "sudo snap refresh",
                }
            elif mgr == "flatpak":
                cmds = {
                    "install": f"flatpak install -y {pkgs}",
                    "remove": f"flatpak uninstall -y {pkgs}",
                    "list": "flatpak list",
                    "search": f"flatpak search {pkgs}",
                    "update": "flatpak update -y",
                    "upgrade": "flatpak update -y",
                }
            else:
                return err(f"unknown manager '{mgr}'. Use apt, pip, pip3, snap, or flatpak")

            cmd = cmds.get(action)
            if not cmd:
                return err(f"unknown action '{action}' for {mgr}")
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600, env=env)
            out = r.stdout.rstrip()
            if r.stderr.strip():
                out += f"\nSTDERR:\n{r.stderr.rstrip()}"
            out += f"\nExit: {r.returncode}"
            return ok(out)

        elif name == "download_file":
            url = args.get("url")
            if not url:
                return err("url is required")
            dest = args.get("destination") or str(Path.home() / "Downloads")
            timeout = int(args.get("timeout", 300))
            Path(dest).expanduser().mkdir(parents=True, exist_ok=True)
            cmd = f"wget -P '{dest}' --timeout={timeout} '{url}'"
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout + 10)
            out = r.stdout.rstrip() or r.stderr.rstrip()
            return ok(out + f"\nExit: {r.returncode}")

        elif name == "extract_archive":
            archive = args.get("archive")
            if not archive:
                return err("archive is required")
            p = _resolve(archive)
            if not p.exists():
                return err(f"not found: {archive}")
            dest = args.get("destination") or str(p.parent)
            Path(dest).mkdir(parents=True, exist_ok=True)
            n = p.name.lower()
            if n.endswith(".zip"):
                cmd = f"unzip -o '{p}' -d '{dest}'"
            elif n.endswith((".tar.gz", ".tgz")):
                cmd = f"tar -xzf '{p}' -C '{dest}'"
            elif n.endswith((".tar.bz2", ".tbz2")):
                cmd = f"tar -xjf '{p}' -C '{dest}'"
            elif n.endswith((".tar.xz", ".txz")):
                cmd = f"tar -xJf '{p}' -C '{dest}'"
            elif n.endswith(".tar"):
                cmd = f"tar -xf '{p}' -C '{dest}'"
            elif n.endswith(".7z"):
                cmd = f"7z x '{p}' -o'{dest}' -y"
            elif n.endswith(".rar"):
                cmd = f"unrar x '{p}' '{dest}/'"
            else:
                return err(f"unsupported archive format: {p.name}")
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
            out = r.stdout.rstrip() or r.stderr.rstrip() or "Done"
            return ok(out + f"\nExit: {r.returncode}")

        elif name == "compress_files":
            sources = args.get("sources")
            output = args.get("output")
            if not sources or not output:
                return err("sources and output are required")
            src_str = " ".join(f"'{s}'" for s in sources)
            if output.endswith(".zip"):
                cmd = f"zip -r '{output}' {src_str}"
            elif output.endswith((".tar.gz", ".tgz")):
                cmd = f"tar -czf '{output}' {src_str}"
            else:
                return err("output must end in .zip or .tar.gz")
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
            out = r.stdout.rstrip() or r.stderr.rstrip() or "Done"
            return ok(out + f"\nExit: {r.returncode}")

        elif name == "service_control":
            action = args.get("action", "").lower()
            svc = args.get("service", "")
            if action == "list":
                cmd = "systemctl list-units --type=service --state=running --no-pager"
            elif action in ("start", "stop", "restart", "enable", "disable"):
                if not svc:
                    return err("service name is required")
                cmd = f"sudo systemctl {action} {svc}"
            elif action == "status":
                cmd = f"systemctl status {svc} --no-pager" if svc else "systemctl --no-pager"
            else:
                return err(f"unknown action: {action}")
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            out = r.stdout.rstrip() or r.stderr.rstrip()
            return ok(out + f"\nExit: {r.returncode}")

        elif name == "run_background":
            command = args.get("command")
            if not command:
                return err("command is required")
            cwd = args.get("cwd") or str(Path.home())
            label = args.get("label") or command[:60]
            proc = subprocess.Popen(
                command, shell=True, cwd=cwd,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            _bg_procs[proc.pid] = {"pid": proc.pid, "label": label, "command": command, "proc": proc}
            return ok(f"Started background process PID={proc.pid}: {label}")

        elif name == "list_background":
            if not _bg_procs:
                return ok("No background processes in this session.")
            lines = []
            for pid, info in list(_bg_procs.items()):
                proc = info["proc"]
                status = "running" if proc.poll() is None else f"exited({proc.returncode})"
                lines.append(f"PID {pid:6}  [{status:12}]  {info['label']}")
            return ok("\n".join(lines))

        elif name == "open_application":
            target = args.get("target")
            if not target:
                return err("target is required")
            subprocess.Popen(
                f"xdg-open '{target}'", shell=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return ok(f"Opened: {target}")

        elif name == "desktop_notify":
            title = args.get("title", "")
            message = args.get("message", "")
            urgency = args.get("urgency", "normal")
            r = subprocess.run(
                f"notify-send -u {urgency} '{title}' '{message}'",
                shell=True, capture_output=True, text=True, timeout=5,
            )
            return ok("Notification sent." if r.returncode == 0 else f"notify-send failed: {r.stderr.strip()}")

        elif name == "list_mounted_drives":
            r = subprocess.run(
                "lsblk -o NAME,MOUNTPOINT,SIZE,USED,AVAIL,FSTYPE,LABEL,MODEL --json 2>/dev/null",
                shell=True, capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0 and r.stdout.strip():
                try:
                    import json as _j
                    data = _j.loads(r.stdout)
                    lines = ["NAME            MOUNTPOINT           SIZE  USED  AVAIL  TYPE   LABEL"]
                    lines.append("-" * 75)
                    def _walk(devs, indent=0):
                        for d in devs:
                            mp = d.get("mountpoint") or ""
                            line = (
                                f"{'  '*indent}{d.get('name',''):15} "
                                f"{mp:20} {d.get('size',''):6} "
                                f"{d.get('used','') or '':6} {d.get('avail','') or '':6} "
                                f"{d.get('fstype','') or '':6} {d.get('label','') or ''}"
                            )
                            lines.append(line.rstrip())
                            if d.get("children"):
                                _walk(d["children"], indent+1)
                    _walk(data.get("blockdevices", []))
                    return ok("\n".join(lines))
                except Exception:
                    pass
            # fallback
            r2 = subprocess.run("df -h --output=source,target,size,used,avail,fstype 2>/dev/null",
                                 shell=True, capture_output=True, text=True, timeout=10)
            return ok(r2.stdout.rstrip() or "Could not list drives.")

        elif name == "read_folder_memory":
            path = args.get("path")
            if not path:
                return err("path is required")
            p = Path(path).expanduser().resolve()
            md_path = p / "astraeus.md"
            json_path = p / "astraeus.json"
            result_parts = []
            if md_path.exists():
                result_parts.append(f"=== astraeus.md ===\n{md_path.read_text(encoding='utf-8', errors='replace')}")
            else:
                result_parts.append(f"(no astraeus.md in {p} — call write_folder_memory to create one)")
            if json_path.exists():
                try:
                    import json as _j
                    data = _j.loads(json_path.read_text())
                    tags = data.get("tags", [])
                    kws = list(data.get("keywords", {}).keys())[:15]
                    result_parts.append(
                        f"\n=== astraeus.json summary ===\n"
                        f"Last updated: {data.get('last_updated','')[:16]}\n"
                        f"Files: {data.get('file_count',0)} | Size: {data.get('total_size_bytes',0):,} B\n"
                        f"Tags: {', '.join(tags)}\n"
                        f"Top keywords: {', '.join(kws)}"
                    )
                except Exception as e:
                    result_parts.append(f"(astraeus.json parse error: {e})")
            return ok("\n".join(result_parts))

        elif name == "write_folder_memory":
            path = args.get("path")
            if not path:
                return err("path is required")
            p = Path(path).expanduser().resolve()
            if not p.is_dir():
                return err(f"Not a directory: {path}")
            notes = args.get("notes", "")
            activity = args.get("activity", "")
            try:
                from astraeus_memory import _write_memory
                result = _write_memory(p, ai_notes=notes, activity=activity)
                return ok(result)
            except ImportError:
                # Inline fallback if astraeus_memory not importable
                import json as _j
                from collections import Counter
                import re as _re

                json_path = p / "astraeus.json"
                existing: dict = {}
                if json_path.exists():
                    try:
                        existing = _j.loads(json_path.read_text())
                    except Exception:
                        pass

                files_info = []
                file_types: Counter = Counter()
                for entry in sorted(p.iterdir(), key=lambda e: e.name.lower()):
                    if entry.is_file() and entry.name not in {"astraeus.md", "astraeus.json"}:
                        size = 0
                        try:
                            size = entry.stat().st_size
                        except Exception:
                            pass
                        file_types[entry.suffix.lower() or "(no ext)"] += 1
                        files_info.append({"name": entry.name, "size": size, "hint": ""})

                log = existing.get("recent_activity", [])
                if activity:
                    log.insert(0, {"timestamp": datetime.now().isoformat(), "action": activity})

                data = {
                    "folder": str(p),
                    "last_updated": datetime.now().isoformat(),
                    "version": 2,
                    "summary": notes or existing.get("summary", f"{p.name} | {len(files_info)} files"),
                    "file_count": len(files_info),
                    "file_types": dict(file_types.most_common(10)),
                    "total_size_bytes": sum(f["size"] for f in files_info),
                    "key_files": files_info[:20],
                    "tags": existing.get("tags", []),
                    "keywords": existing.get("keywords", {}),
                    "ai_notes": notes or existing.get("ai_notes", ""),
                    "recent_activity": log[:100],
                }
                json_path.write_text(_j.dumps(data, indent=2, ensure_ascii=False))

                md_lines = [
                    f"# Astraeus Memory — `{p.name}`",
                    f"> Path: `{p}`  |  Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                    "", "## Summary", data["summary"], "",
                    "## Files",
                    f"- Count: {data['file_count']}",
                ]
                if notes:
                    md_lines += ["", "## Astraeus Notes", notes]
                if log:
                    md_lines += ["", "## Recent Activity"]
                    for item in log[:10]:
                        md_lines.append(f"- `{item.get('timestamp','')[:16]}` {item.get('action','')}")

                (p / "astraeus.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")
                return ok(f"Memory updated (fallback mode): {p}")

        elif name == "search_all_memory":
            query = args.get("query")
            if not query:
                return err("query is required")
            start = args.get("start_path", "/")
            try:
                from astraeus_memory import FolderMemory
                mem = FolderMemory.__new__(FolderMemory)
                results = mem.search(query, start_path=start)
            except ImportError:
                import json as _j
                import re as _re

                stop = {
                    "the","and","for","are","not","you","can","was","one","our",
                    "that","this","with","from","will","when","did","its",
                }
                words_raw = _re.findall(r'\b[a-zA-ZäöüÄÖÜß]{3,}\b', query.lower())
                query_tokens = set(w for w in words_raw if w not in stop)

                r = subprocess.run(
                    f'find "{start}" -name "astraeus.json" 2>/dev/null',
                    shell=True, capture_output=True, text=True, timeout=45,
                )
                files = [l.strip() for l in r.stdout.splitlines() if l.strip()]
                results = []
                for fpath in files:
                    try:
                        data = _j.loads(Path(fpath).read_text())
                        kw = data.get("keywords", {})
                        tags = set(data.get("tags", []))
                        score = sum(kw.get(w, 0.0) for w in query_tokens)
                        score += 0.4 * sum(1 for t in tags if t in query_tokens)
                        folder_name = Path(data.get("folder", "")).name.lower()
                        score += 0.5 * sum(1 for w in query_tokens if w in folder_name)
                        if score > 0:
                            results.append({
                                "folder": data.get("folder", str(Path(fpath).parent)),
                                "score": round(score, 4),
                                "summary": data.get("summary", ""),
                                "tags": data.get("tags", []),
                                "last_updated": data.get("last_updated", "")[:16],
                            })
                    except Exception:
                        continue
                results.sort(key=lambda x: x["score"], reverse=True)
                results = results[:20]

            if not results:
                return ok(f"No memory files found matching '{query}'.\nHint: the system may not have been scanned yet. Use write_folder_memory or directory_tree to build the index.")

            lines = [f"Memory search results for '{query}' (top {len(results)}):"]
            for i, r in enumerate(results, 1):
                lines.append(
                    f"\n{i}. {r['folder']}\n"
                    f"   Score: {r['score']}  |  Updated: {r['last_updated']}\n"
                    f"   Tags: {', '.join(r['tags'])}\n"
                    f"   Summary: {r['summary'][:120]}"
                )
            return ok("\n".join(lines))

        elif name == "schedule_status":
            import json as _j
            cfg_path = Path.home() / ".config" / "astraeus" / "schedule_config.json"
            if cfg_path.exists():
                cfg = _j.loads(cfg_path.read_text())
            else:
                cfg = {"enabled": True, "shutdown_time": "00:00",
                       "wakeup_time": "08:00", "timezone": "Europe/Berlin",
                       "language": "auto"}
            status = "ENABLED" if cfg.get("enabled", True) else "DISABLED"
            return ok(
                f"Schedule: {status}\n"
                f"Shutdown : {cfg.get('shutdown_time','00:00')} Berlin time\n"
                f"Wakeup   : {cfg.get('wakeup_time','08:00')} Berlin time\n"
                f"Timezone : {cfg.get('timezone','Europe/Berlin')}\n"
                f"Language : {cfg.get('language','auto')}\n"
                f"Config   : {cfg_path}"
            )

        elif name == "schedule_set":
            import json as _j
            cfg_path = Path.home() / ".config" / "astraeus" / "schedule_config.json"
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            cfg = {}
            if cfg_path.exists():
                try:
                    cfg = _j.loads(cfg_path.read_text())
                except Exception:
                    pass
            if not cfg:
                cfg = {"enabled": True, "shutdown_time": "00:00",
                       "wakeup_time": "08:00", "timezone": "Europe/Berlin",
                       "language": "auto"}
            changed = []
            if "shutdown_time" in args:
                cfg["shutdown_time"] = args["shutdown_time"]
                changed.append(f"shutdown → {args['shutdown_time']}")
            if "wakeup_time" in args:
                cfg["wakeup_time"] = args["wakeup_time"]
                changed.append(f"wakeup → {args['wakeup_time']}")
            if "enabled" in args:
                cfg["enabled"] = args["enabled"]
                changed.append(f"enabled → {args['enabled']}")
            if "language" in args:
                cfg["language"] = args["language"]
                changed.append(f"language → {args['language']}")
            cfg_path.write_text(_j.dumps(cfg, indent=2))
            return ok(
                f"Schedule updated: {', '.join(changed) or 'no changes'}\n"
                f"Shutdown : {cfg['shutdown_time']} Berlin time\n"
                f"Wakeup   : {cfg['wakeup_time']} Berlin time\n"
                f"Note: restart Astraeus for new times to take effect."
            )

        elif name == "prepare_for_vision":
            path = args.get("path", "")
            timestamp = float(args.get("timestamp", 5.0))
            page = int(args.get("page", 1))
            try:
                from astraeus_vision import (
                    file_to_base64, url_to_base64, ALL_VISUAL,
                )
                if path.startswith(("http://", "https://")):
                    mime, b64 = url_to_base64(path, timestamp)
                else:
                    mime, b64 = file_to_base64(path, timestamp=timestamp, page=page)
                return ok(
                    f"[VISION_IMAGE:{mime}]\n{b64}\n[/VISION_IMAGE]\n"
                    f"Image prepared from: {path}\n"
                    f"The IDE will attach this to your next model call automatically."
                )
            except Exception as e:
                return err(f"Vision preparation failed: {e}")

        elif name == "screen_capture":
            region = args.get("region")
            window_title = args.get("window_title")
            try:
                from astraeus_vision import screenshot_to_base64
                mime, b64 = screenshot_to_base64(region=region, window_title=window_title)
                return ok(
                    f"[VISION_IMAGE:{mime}]\n{b64}\n[/VISION_IMAGE]\n"
                    f"Screenshot captured."
                )
            except Exception as e:
                return err(f"Screenshot failed: {e}")

        elif name == "call_claude":
            prompt = args.get("prompt")
            if not prompt:
                return err("prompt is required")
            context = args.get("context", "")
            model = args.get("model", "claude-sonnet-4-6")
            image_b64 = args.get("image_base64", "")
            image_mime = args.get("image_mime", "image/jpeg")
            max_tokens = int(args.get("max_tokens", 4096))

            # Only Anthropic Claude models allowed — no other AI companies
            allowed = ("claude-opus", "claude-sonnet", "claude-haiku")
            if not any(a in model.lower() for a in allowed):
                return err(
                    f"Only Anthropic Claude models are allowed. "
                    f"Use: claude-opus-4-7, claude-sonnet-4-6, or claude-haiku-4-5"
                )

            # Load API key
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if not api_key:
                cfg_path = Path.home() / ".config" / "astraeus" / "claude_api.json"
                if cfg_path.exists():
                    import json as _j
                    api_key = _j.loads(cfg_path.read_text()).get("api_key", "")
            if not api_key:
                return err(
                    "No ANTHROPIC_API_KEY found.\n"
                    "Set it with:\n"
                    "  export ANTHROPIC_API_KEY=sk-ant-...\n"
                    "Or save to: ~/.config/astraeus/claude_api.json\n"
                    '  {"api_key": "sk-ant-..."}'
                )

            full_prompt = f"{context}\n\n{prompt}" if context else prompt
            content: list[dict] = [{"type": "text", "text": full_prompt}]
            if image_b64:
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image_mime,
                        "data": image_b64,
                    },
                })

            import json as _j
            import urllib.request
            import urllib.error

            payload = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": content}],
            }
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=_j.dumps(payload).encode(),
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    result = _j.loads(resp.read())
                text = result["content"][0]["text"]
                return ok(f"[Claude {model}]\n\n{text}")
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")
                return err(f"Claude API error {e.code}: {body}")

        elif name == "convert_to_pdf":
            input_path = args.get("input")
            if not input_path:
                return err("input is required")
            inp = _resolve(input_path)
            if not inp.exists():
                return err(f"not found: {input_path}")
            output_path = args.get("output") or str(inp.with_suffix(".pdf"))
            paper = args.get("paper", "a4")
            margin = args.get("margin", "2.5cm")
            font_size = args.get("font_size", "11pt")

            # Try pandoc with xelatex (best quality)
            chk = subprocess.run("which pandoc", shell=True, capture_output=True)
            if chk.returncode == 0:
                geo = f"geometry:margin={margin}"
                cmd = (
                    f"pandoc '{inp}' -o '{output_path}' "
                    f"--pdf-engine=xelatex "
                    f"-V {geo} -V papersize={paper} -V fontsize={font_size} "
                    f"-V mainfont='DejaVu Serif' -V monofont='DejaVu Sans Mono' "
                    f"--highlight-style=tango 2>&1"
                )
                r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=90)
                if r.returncode == 0:
                    return ok(f"PDF created: {output_path}")
                # Fallback: pandoc without xelatex
                cmd2 = (
                    f"pandoc '{inp}' -o '{output_path}' "
                    f"-V {geo} -V papersize={paper} -V fontsize={font_size} 2>&1"
                )
                r2 = subprocess.run(cmd2, shell=True, capture_output=True, text=True, timeout=90)
                if r2.returncode == 0:
                    return ok(f"PDF created: {output_path}")
                return err(f"pandoc failed:\n{r.stdout}\nHint: sudo apt install texlive-xetex")

            # Try LibreOffice
            chk2 = subprocess.run("which libreoffice", shell=True, capture_output=True)
            if chk2.returncode == 0:
                out_dir = str(Path(output_path).parent)
                r = subprocess.run(
                    f"libreoffice --headless --convert-to pdf '{inp}' --outdir '{out_dir}'",
                    shell=True, capture_output=True, text=True, timeout=90,
                )
                if r.returncode == 0:
                    return ok(f"PDF created via LibreOffice in {out_dir}")
                return err(f"LibreOffice failed: {r.stderr.rstrip()}")

            return err(
                "No PDF converter found.\n"
                "Install pandoc: sudo apt install pandoc texlive-xetex\n"
                "Or LibreOffice: sudo apt install libreoffice"
            )

        elif name == "setup_email":
            import json as _json
            imap_host = args.get("imap_host")
            imap_port = int(args.get("imap_port", 993))
            username = args.get("username")
            password = args.get("password")
            smtp_host = args.get("smtp_host") or imap_host.replace("imap.", "smtp.", 1)
            smtp_port = int(args.get("smtp_port", 587))
            display_name = args.get("display_name", "")

            if not all([imap_host, username, password]):
                return err("imap_host, username, and password are required")

            config_dir = Path.home() / ".config" / "astraeus"
            config_dir.mkdir(parents=True, exist_ok=True)
            config_path = config_dir / "email.json"

            config = {
                "imap": {"host": imap_host, "port": imap_port,
                         "username": username, "password": password},
                "smtp": {"host": smtp_host, "port": smtp_port,
                         "username": username, "password": password},
                "display_name": display_name or username,
            }
            config_path.write_text(_json.dumps(config, indent=2))
            os.chmod(str(config_path), 0o600)
            return ok(f"Email configured for {username}\nConfig: {config_path} (permissions 600)")

        elif name == "read_emails":
            import imaplib
            import email as _email
            from email.header import decode_header as _dh
            import json as _json
            from datetime import datetime, timedelta

            config_path = Path.home() / ".config" / "astraeus" / "email.json"
            if not config_path.exists():
                return err(
                    "Email not configured. Use setup_email first.\n"
                    "Example: setup_email(imap_host='imap.gmail.com', username='you@gmail.com', password='yourpassword')"
                )

            cfg = _json.loads(config_path.read_text())
            ic = cfg.get("imap", {})
            host, port = ic.get("host"), int(ic.get("port", 993))
            user, pw = ic.get("username"), ic.get("password")
            if not all([host, user, pw]):
                return err("Incomplete email config. Re-run setup_email.")

            count = int(args.get("count", 10))
            folder = args.get("folder", "INBOX")
            date_arg = (args.get("date") or "TODAY").upper()
            unread_only = args.get("unread_only", False)

            def _decode(s):
                if not s:
                    return ""
                parts = _dh(s)
                out = []
                for part, enc in parts:
                    if isinstance(part, bytes):
                        out.append(part.decode(enc or "utf-8", errors="replace"))
                    else:
                        out.append(str(part))
                return " ".join(out)

            try:
                mail = imaplib.IMAP4_SSL(host, port)
                mail.login(user, pw)
                mail.select(folder)

                if date_arg == "TODAY":
                    since = datetime.now().strftime("%d-%b-%Y")
                    criteria = f'SINCE "{since}"'
                elif date_arg == "YESTERDAY":
                    since = (datetime.now() - timedelta(days=1)).strftime("%d-%b-%Y")
                    before = datetime.now().strftime("%d-%b-%Y")
                    criteria = f'SINCE "{since}" BEFORE "{before}"'
                else:
                    criteria = f'SINCE "{date_arg}"'

                if unread_only:
                    criteria = f"UNSEEN {criteria}"

                _, data = mail.search(None, f"({criteria})")
                ids = data[0].split()
                if not ids:
                    mail.close()
                    mail.logout()
                    return ok(f"No emails found (filter: {criteria}).")

                selected = ids[-count:]
                results = []
                for mid in selected:
                    _, mdata = mail.fetch(mid, "(RFC822)")
                    msg = _email.message_from_bytes(mdata[0][1])
                    subject = _decode(msg.get("Subject", "(no subject)"))
                    sender = _decode(msg.get("From", "(unknown)"))
                    date_str = msg.get("Date", "")
                    msg_id_hdr = msg.get("Message-ID", "")

                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            ct = part.get_content_type()
                            cd = str(part.get("Content-Disposition", ""))
                            if ct == "text/plain" and "attachment" not in cd:
                                cs = part.get_content_charset() or "utf-8"
                                body = part.get_payload(decode=True).decode(cs, errors="replace")
                                break
                    else:
                        cs = msg.get_content_charset() or "utf-8"
                        body = msg.get_payload(decode=True).decode(cs, errors="replace")

                    results.append(
                        f"━━━ Email {len(results)+1} ━━━\n"
                        f"From:       {sender}\n"
                        f"Date:       {date_str}\n"
                        f"Subject:    {subject}\n"
                        f"Message-ID: {msg_id_hdr}\n"
                        f"\n{body.strip()[:3000]}\n"
                    )

                mail.close()
                mail.logout()
                return ok(f"{len(results)} email(s) fetched:\n\n" + "\n".join(results))

            except imaplib.IMAP4.error as e:
                return err(f"IMAP login failed: {e}\nCheck credentials with setup_email.")
            except Exception as e:
                return err(f"{type(e).__name__}: {e}")

        elif name == "draft_email":
            import json as _json
            from datetime import datetime

            to = args.get("to", "")
            subject = args.get("subject", "")
            body = args.get("body", "")
            reply_id = args.get("reply_to_message_id", "")
            save_path = args.get("path")

            if not save_path:
                safe_subj = re.sub(r'[^\w\s-]', '', subject)[:40].strip().replace(" ", "_")
                ts = datetime.now().strftime("%Y%m%d_%H%M")
                save_path = str(Path.home() / "Drafts" / f"draft_{ts}_{safe_subj}.eml")

            Path(save_path).parent.mkdir(parents=True, exist_ok=True)

            # Try to read display name from config
            display_name = ""
            try:
                cfg_path = Path.home() / ".config" / "astraeus" / "email.json"
                if cfg_path.exists():
                    cfg = _json.loads(cfg_path.read_text())
                    display_name = cfg.get("display_name", cfg["imap"]["username"])
                    from_addr = f"{display_name} <{cfg['imap']['username']}>"
                else:
                    from_addr = "Draft"
            except Exception:
                from_addr = "Draft"

            headers = [
                f"From: {from_addr}",
                f"To: {to}",
                f"Subject: {subject}",
                f"Date: {datetime.now().strftime('%a, %d %b %Y %H:%M:%S +0000')}",
                "MIME-Version: 1.0",
                "Content-Type: text/plain; charset=utf-8",
                "X-Status: Draft",
            ]
            if reply_id:
                headers += [f"In-Reply-To: {reply_id}", f"References: {reply_id}"]

            eml = "\n".join(headers) + "\n\n" + body
            Path(save_path).write_text(eml, encoding="utf-8")

            return ok(
                f"Draft saved: {save_path}\n\n"
                f"--- PREVIEW ---\n"
                f"To: {to}\n"
                f"Subject: {subject}\n\n"
                f"{body}\n"
                f"--- END PREVIEW ---\n\n"
                f"NOT sent. Show this to the user and ask them to confirm before sending."
            )

        else:
            raise ValueError(f"Unknown tool: {name}")

    except PermissionError as e:
        return err(str(e))
    except subprocess.TimeoutExpired:
        return err("command timed out")
    except Exception as e:
        logger.error(f"Tool error [{name}]: {e}")
        return err(f"{type(e).__name__}: {e}")


async def main():
    logger.info(f"Starting {SERVER_NAME} v{SERVER_VERSION}" +
                (f"  workspace={_WORKSPACE_ROOT}" if _WORKSPACE_ROOT else "  (full system access)"))
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name=SERVER_NAME,
                server_version=SERVER_VERSION,
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
