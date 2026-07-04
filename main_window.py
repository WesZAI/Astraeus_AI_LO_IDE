# ==========================================
# Copyright (c) 2026 Gabriela Berger AI Oberland
# All Rights Reserved.
# This code is subject to the custom NON-COMMERCIAL 
# & ANTI-CORPORATE LICENSE (Maximum 20 PCs) found in the LICENSE file.
# ==========================================
import os
# Allow running under WSL/WSLg where XCB/Xlib threading can fail.
# Setting `LIBXCB_ALLOW_SLOPPY_LOCK=1` avoids the xcb_xlib_threads_sequence_lost assertion
# when the system's X libraries are not fully thread-safe. Set before any X-related
# library (tkinter) is imported.
os.environ.setdefault("LIBXCB_ALLOW_SLOPPY_LOCK", "1")

import tkinter as tk
from tkinter import scrolledtext, messagebox, ttk, Menu, filedialog, Frame, Entry, Button, Label
# The following imports are project-specific. Commented out so this file
# can be run standalone for testing. Do not delete — uncomment when
# running inside the full project.
from network_manager import NetworkManager
from database_manager import DatabaseManager, SQLiteMemoryManager
from memory_bridge import MemoryBridge
from connect_terminal import TerminalConnector
from config import AppConfig
import time
import shlex
import json
import os
import subprocess
import threading
import sys
import shutil
from pathlib import Path
from tkinter import simpledialog
try:
    import jinja2
except Exception:
    jinja2 = None

import re as _re

# Matches all ANSI / VT100 escape sequences:
#   CSI  — ESC [ ... letter   (colours, cursor, bracket-paste mode, etc.)
#   OSC  — ESC ] ... BEL/ST   (terminal title, etc.)
#   DCS/SOS/PM/APC — ESC P/X/^/_ ... ST
#   Single-char ESC sequences
_ANSI_RE = _re.compile(
    r'\x1b'
    r'(?:'
    r'\[[0-9;?]*[A-Za-z]'           # CSI  — ESC [ params letter
    r'|\][^\x07\x1b]*(?:\x07|\x1b\\)'  # OSC  — ESC ] text BEL|ST
    r'|[PX^_].*?\x1b\\'             # DCS/SOS/PM/APC
    r'|\([A-Z]'                     # character-set selection
    r'|[ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz\\]'  # single-char
    r')',
    _re.DOTALL,
)
# Strip lone control characters (BEL, BS, SI/SO, etc.) but keep \n, \r, \t
_CTRL_RE = _re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')

# Maximum number of workspace tabs open at the same time.
# When this limit is exceeded the oldest (leftmost) tab is closed automatically.
MAX_EDITOR_TABS = 5


def _strip_ansi(text: str) -> str:
    """Remove all ANSI escape sequences and bare control characters from text."""
    text = _ANSI_RE.sub('', text)
    text = _CTRL_RE.sub('', text)
    # Collapse carriage-returns: \r without following \n just resets the line;
    # simplest treatment for a text widget is to drop them.
    text = text.replace('\r\n', '\n').replace('\r', '')
    return text


def _strip_for_tts(text: str) -> str:
    """Remove markdown, XML tags, code blocks, emoticons, tables, and tool output from text before TTS."""
    import re as _r
    
    # Remove tool call blocks
    text = _r.sub(r'<tool_call>.*?</tool_call>', '', text, flags=_r.DOTALL)
    text = _r.sub(r'<bash>.*?</bash>', '', text, flags=_r.DOTALL)
    # Remove all XML/HTML tags
    text = _r.sub(r'<[^>]+>', '', text)
    # Remove HTML entities (Sonderzeichen codes) like &nbsp;, &#1234;
    text = _r.sub(r'&[a-zA-Z0-9#]+;', ' ', text)
    # Remove code fences and inline code
    text = _r.sub(r'```.*?```', '', text, flags=_r.DOTALL)
    text = _r.sub(r'`[^`]+`', '', text)
    # Remove markdown tables (lines containing pipe characters)
    text = _r.sub(r'\|.*\|', '', text)
    text = _r.sub(r'\+-[+-]+\+', '', text) # ASCII tables
    # Remove URLs
    text = _r.sub(r'https?://\S+', '', text)
    # Remove Emojis and other graphical unicode blocks
    text = _r.sub(r'[\U00010000-\U0010ffff]', '', text)
    text = _r.sub(r'[\u2600-\u27BF]', '', text)
    # Remove Markdown formatting and special characters
    text = _r.sub(r'[#*_~>|\\/\[\]{}]', ' ', text)
    # Collapse whitespace
    text = _r.sub(r'\s+', ' ', text)
    return text.strip()


class MainWindow:
    def __init__(self, root):
        self.root = root
        self.root.title("AI_Assistant IDE")
        self.root.geometry("1600x1200")

        # Dark theme colors
        self.bg_color = "#2b0036"         # deep violet background
        self.fg_color = "#bfa3bf"         # muted, darker lavender foreground
        self.accent_color = "#b08b3b"     # muted gold for accents/lines
        self.secondary_color = "#3a0a4a"  # slightly lighter violet panels
        self.entry_bg = "#43163a"         # muted dark for entries
        self.button_bg = "#8b3a4b"        # dark-rose for buttons
        self.button_fg = self.accent_color  # replace white with gold accent for button text

        self.root.configure(bg=self.bg_color)

        # used to debounce resize adjustments
        self._adjust_after_id = None
        # last applied terminal min height
        self._terminal_min_h = None
        # command history for the terminal input boxes
        self._term_history: list = []
        self._term_history_idx: int = 0

        # load application model configs BEFORE creating widgets
        try:
            self.app_config = AppConfig()
        except Exception:
            self.app_config = None

        self.create_widgets()
        # track whether a chat session was started to avoid repeated "Started" messages
        self._chat_started = False
        self._model_proc = None
        self._model_log_thread = None
        self._model_log_stop = threading.Event()
        self.system_prompts = self._load_system_prompts()

        self._new_editor_tab()  # create the first empty workspace tab
        self._load_api_keys()   # load saved API keys into os.environ before first use
        self.network_manager = NetworkManager()
        self.db_manager = DatabaseManager('chat_history.json')
        self.memory_manager = SQLiteMemoryManager('memory.sqlite3')
        self.memory_bridge = MemoryBridge('memory.sqlite3')
        self._current_file_path = None
        self._explorer_watcher_stop = None

        from ide_agent import IDEAgent
        try:
            self.ide_agent = IDEAgent(self)
        except Exception as e:
            print(f"IDEAgent init failed: {e}")
            self.ide_agent = None

        # Voice engine (Vosk STT + Piper TTS)
        self._voice_tts_on = False
        self._voice_engine = None
        self._schedule = None
        self._init_voice()

        # ensure we clean up on window close
        try:
            self.root.protocol("WM_DELETE_WINDOW", self.on_exit)
        except Exception:
            pass

    def create_widgets(self):
        # Menu Bar
        self.menu_bar = Menu(self.root, bg=self.secondary_color, fg=self.fg_color, tearoff=0)
        self.root.config(menu=self.menu_bar)

        self.file_menu = Menu(self.menu_bar, bg=self.secondary_color, fg=self.fg_color, tearoff=0)
        self.file_menu.add_command(label="Open Folder", command=self.open_folder)
        self.file_menu.add_command(label="New File", command=self.new_file)
        self.file_menu.add_command(label="Save File", command=self.save_file)
        self.file_menu.add_command(label="Save As...", command=self.save_file_as)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Exit", command=self.root.quit)
        self.menu_bar.add_cascade(label="File", menu=self.file_menu)

        # Main Container (use grid to enforce 3-column layout: 25% / 50% / 25%)
        self.main_container = Frame(self.root, bg=self.bg_color)
        self.main_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Configure columns: left (explorer) 1, center (workspace+terminal) 4, right (chat) 1
        self.main_container.grid_rowconfigure(0, weight=1)
        self.main_container.grid_columnconfigure(0, weight=1)
        self.main_container.grid_columnconfigure(1, weight=4)
        self.main_container.grid_columnconfigure(2, weight=1)

        # Explorer (left column, full height)
        self.explorer_frame = Frame(self.main_container, bg=self.secondary_color)
        self.explorer_frame.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)

        self.explorer_label = Label(self.explorer_frame, text="Explorer", bg=self.secondary_color, fg=self.fg_color, font=('Arial', 12, 'bold'))
        self.explorer_label.pack(fill=tk.X, padx=5, pady=2)

        self.path_var = tk.StringVar(value=os.path.expanduser("~"))
        self.path_entry = Entry(self.explorer_frame, textvariable=self.path_var, bg=self.entry_bg, fg=self.fg_color, insertbackground=self.fg_color)
        self.path_entry.pack(fill=tk.X, padx=5, pady=2)

        self.browse_btn = Button(self.explorer_frame, text="Browse", command=self.open_folder, bg=self.button_bg, fg=self.button_fg)
        self.browse_btn.pack(fill=tk.X, padx=5, pady=2)

        self.refresh_btn = Button(self.explorer_frame, text="🔄 Refresh", command=self.refresh_file_tree, bg=self.button_bg, fg=self.button_fg)
        self.refresh_btn.pack(fill=tk.X, padx=5, pady=2)

        self.file_tree = ttk.Treeview(self.explorer_frame)
        self.file_tree.pack(expand=True, fill='both', padx=5, pady=5)
        self.file_tree.bind('<<TreeviewSelect>>', self.on_file_select)
        self.file_tree.bind('<Double-1>', self.on_file_double_click)
        self.file_tree.bind('<<TreeviewOpen>>', self._on_tree_expand)
        self.file_tree.bind('<Button-3>', self._show_explorer_menu)
        self.file_tree.bind('<Button-2>', self._show_explorer_menu)  # macOS middle-click

        # Center column: workspace (top) and terminal (bottom)
        self.center_container = Frame(self.main_container, bg=self.bg_color)
        self.center_container.grid(row=0, column=1, sticky='nsew', padx=5, pady=5)
        # Force the Terminal row to be very small, and Workspace to be very large
        self.center_container.grid_rowconfigure(0, weight=8) # Keep Workspace larger, but leave room for Terminal
        self.center_container.grid_rowconfigure(1, weight=0, minsize=280) # Terminal should match the chat height
        self.center_container.grid_columnconfigure(0, weight=1)

        # Workspace (top of center)
        self.editor_frame = Frame(self.center_container, bg=self.secondary_color)
        self.editor_frame.grid(row=0, column=0, sticky='nsew', padx=0, pady=(0,5))

        self.editor_label = Label(self.editor_frame, text="Workspace", bg=self.secondary_color, fg=self.fg_color, font=('Arial', 12, 'bold'))
        self.editor_label.pack(fill=tk.X, padx=5, pady=2)

        # Workspace menu / dropdown (placeholder - user will add functions later)
        self.workspace_menu_frame = Frame(self.editor_frame, bg=self.secondary_color, height=30)
        self.workspace_menu_frame.pack(fill=tk.X, padx=5, pady=(0,2))

        self.new_button = Button(self.workspace_menu_frame, text="New", command=self.clear_workspace,
                                 bg=self.button_bg, fg=self.button_fg)
        self.new_button.pack(side=tk.LEFT, padx=2)

        self.save_button = Button(self.workspace_menu_frame, text="Save", command=self.save_file,
                                  bg=self.button_bg, fg=self.button_fg)
        self.save_button.pack(side=tk.LEFT, padx=2)

        self.save_as_button = Button(self.workspace_menu_frame, text="Save As...", command=self.save_file_as,
                                     bg=self.button_bg, fg=self.button_fg)
        self.save_as_button.pack(side=tk.LEFT, padx=2)

        # Shows which file is currently open — updated by set_current_file_path / save_file
        self.open_file_label_var = tk.StringVar(value="(keine Datei geöffnet)")
        Label(self.workspace_menu_frame, textvariable=self.open_file_label_var,
              bg=self.secondary_color, fg=self.accent_color,
              font=('Arial', 9, 'italic')).pack(side=tk.LEFT, padx=8)

        # Second action row: diff / apply code from chat / delete backups
        self.workspace_action_bar = Frame(self.editor_frame, bg=self.secondary_color)
        self.workspace_action_bar.pack(fill=tk.X, padx=5, pady=(0, 2))
        Button(self.workspace_action_bar, text="Diff",
               command=self._show_diff,
               bg=self.button_bg, fg=self.button_fg).pack(side=tk.LEFT, padx=2)
        Button(self.workspace_action_bar, text="Apply Code",
               command=self._apply_chat_code_to_file,
               bg=self.button_bg, fg=self.button_fg).pack(side=tk.LEFT, padx=2)
        Button(self.workspace_action_bar, text="Del Backups",
               command=self._clean_backups,
               bg=self.button_bg, fg=self.button_fg).pack(side=tk.LEFT, padx=2)

        # Workspace editor — tabbed notebook (replaces single ScrolledText)
        self._workspace_tabs = []
        self._workspace_notebook = ttk.Notebook(self.editor_frame)
        self._workspace_notebook.pack(expand=True, fill='both', padx=5, pady=(0, 5))
        self._workspace_notebook.bind('<<NotebookTabChanged>>', self._on_workspace_tab_changed)
        self._workspace_notebook.bind('<Button-3>', self._on_workspace_tab_rightclick)
        self._workspace_notebook.bind('<Button-2>', self._on_workspace_tab_rightclick)

        # Chat (right column, full height)
        self.chat_frame = Frame(self.main_container, bg=self.secondary_color)
        self.chat_frame.grid(row=0, column=2, sticky='nsew', padx=5, pady=5)

        self.chat_label = Label(self.chat_frame, text="Chat", bg=self.secondary_color, fg=self.fg_color, font=('Arial', 12, 'bold'))
        self.chat_label.pack(fill=tk.X, padx=5, pady=2)

        # Model Selection Dropdown (top of right column)
        self.model_bar = Frame(self.chat_frame, bg=self.secondary_color)
        self.model_bar.pack(fill=tk.X, padx=5, pady=(0,5))
        self.model_label = Label(self.model_bar, text="Select Model:", bg=self.secondary_color, fg=self.fg_color)
        self.model_label.pack(side=tk.LEFT, padx=5)
        self.model_var = tk.StringVar(value="AI_Assistant_Mistral")
        self.model_dropdown = ttk.Combobox(self.model_bar, textvariable=self.model_var, state='readonly')
        # Populate from config
        model_names = list(self.app_config.models.keys()) if self.app_config else ["AI_Assistant_Mistral"]
        self.model_dropdown['values'] = model_names
        self.model_dropdown.pack(side=tk.LEFT, padx=5)
        self.model_dropdown.bind('<<ComboboxSelected>>', self._on_model_selected)
        # Note: Chat is started from the Send area; remove duplicate Start Chat button

        # Model server controls: Start/Stop selected model (only one at a time)
        self.model_start_btn = Button(self.model_bar, text="Start Model", command=self.start_model_server, bg=self.button_bg, fg=self.button_fg)
        self.model_start_btn.pack(side=tk.LEFT, padx=5)
        self.model_stop_btn = Button(self.model_bar, text="Stop Model", command=self.stop_model_server, bg=self.button_bg, fg=self.button_fg)
        self.model_stop_btn.pack(side=tk.LEFT, padx=5)
        # Allow editing/loading a chat template for the selected model (paste tokenizer.chat_template here)
        self.edit_template_btn = Button(self.model_bar, text="Edit Template", command=self._edit_model_template, bg=self.button_bg, fg=self.button_fg)
        self.edit_template_btn.pack(side=tk.LEFT, padx=5)
        self.api_keys_btn = Button(self.model_bar, text="API Keys", command=self._edit_api_keys, bg=self.button_bg, fg=self.button_fg)
        self.api_keys_btn.pack(side=tk.LEFT, padx=5)

        # Chat display (Agent Chat history)
        self.chat_display = scrolledtext.ScrolledText(self.chat_frame, wrap=tk.WORD, bg=self.entry_bg, fg=self.accent_color, insertbackground=self.accent_color)
        self.chat_display.pack(expand=True, fill='both', padx=5, pady=5)
        self.chat_display.tag_configure('you',      foreground='#e8c97a', font=('Arial', 10, 'bold'))
        self.chat_display.tag_configure('you_text', foreground='#e8c97a')
        self.chat_display.tag_configure('ai',       foreground=self.accent_color, font=('Arial', 10, 'bold'))
        self.chat_display.tag_configure('ai_text',  foreground=self.accent_color)
        self.chat_display.tag_configure('system',   foreground='#888888', font=('Arial', 9, 'italic'))
        self.chat_display.configure(state='disabled')

        # Allow text selection and Ctrl+C/A even in disabled state
        def _chat_copy(event=None):
            try:
                sel = self.chat_display.get(tk.SEL_FIRST, tk.SEL_LAST)
                self.chat_display.clipboard_clear()
                self.chat_display.clipboard_append(sel)
            except tk.TclError:
                pass
            return "break"

        def _chat_select_all(event=None):
            self.chat_display.tag_add(tk.SEL, "1.0", tk.END)
            return "break"

        self.chat_display.bind("<Control-c>", _chat_copy)
        self.chat_display.bind("<Control-C>", _chat_copy)
        self.chat_display.bind("<Control-a>", _chat_select_all)
        self.chat_display.bind("<Control-A>", _chat_select_all)

        # Send button area: split into Send and Start Chat (Start Chat will ensure model is running)
        self.send_bar = Frame(self.chat_frame, bg=self.secondary_color)
        self.send_bar.pack(fill=tk.X, padx=5, pady=2)
        self.send_button = Button(self.send_bar, text="Send", command=self.send_message, bg=self.button_bg, fg=self.button_fg)
        self.send_button.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.start_chat_split_btn = Button(self.send_bar, text="Start Chat", command=self.start_session, bg=self.button_bg, fg=self.button_fg)
        self.start_chat_split_btn.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Voice buttons
        self.mic_button = Button(
            self.send_bar, text="🎤", width=3,
            command=self._voice_push_to_talk,
            bg=self.button_bg, fg=self.button_fg,
            font=('Arial', 12),
        )
        self.mic_button.pack(side=tk.LEFT, padx=(4, 0))

        self.tts_button = Button(
            self.send_bar, text="🔇", width=3,
            command=self._voice_toggle_tts,
            bg=self.button_bg, fg="#888888",
            font=('Arial', 12),
        )
        self.tts_button.pack(side=tk.LEFT, padx=(2, 0))

        self.stt_lang_button = Button(
            self.send_bar, text="DE", width=3,
            command=self._voice_toggle_language,
            bg=self.button_bg, fg=self.accent_color,
            font=('Arial', 9, 'bold'),
        )
        self.stt_lang_button.pack(side=tk.LEFT, padx=(2, 0))

        self.voice_status_label = Label(
            self.send_bar, text="", width=16,
            bg=self.secondary_color, fg="#888888",
            font=('Arial', 9),
        )
        self.voice_status_label.pack(side=tk.LEFT, padx=(6, 2))

        # My Chat area (bottom input)
        self.chat_input = scrolledtext.ScrolledText(self.chat_frame, wrap=tk.WORD, height=14, bg=self.entry_bg, fg=self.fg_color, insertbackground=self.fg_color)
        self.chat_input.pack(fill=tk.X, padx=5, pady=(0,5))

        # Terminal (bottom of center)
        self.terminal_frame = Frame(self.center_container, bg=self.secondary_color)
        self.terminal_frame.grid(row=1, column=0, sticky='nsew', padx=0, pady=(0,5))

        self.terminal_label = Label(self.terminal_frame, text="Terminal", bg=self.secondary_color, fg=self.fg_color, font=('Arial', 12, 'bold'))
        self.terminal_label.pack(fill=tk.X, padx=5, pady=2)

        self.terminal_options_bar = Frame(self.terminal_frame, bg=self.secondary_color)
        self.terminal_options_bar.pack(fill=tk.X, padx=5, pady=(0, 2))

        self.shell_var = tk.StringVar(value="Bash")
        self.shell_selector = ttk.Combobox(self.terminal_options_bar, textvariable=self.shell_var, state='readonly')
        self.shell_selector['values'] = ["Bash"]
        self.shell_selector.pack(side=tk.LEFT, padx=5)

        self.terminal_start_button = Button(self.terminal_options_bar, text="Start", command=self.start_terminal, bg=self.button_bg, fg=self.button_fg)
        self.terminal_start_button.pack(side=tk.LEFT, padx=5)
        self.terminal_start_button.bind('<Return>', self.on_terminal_start_enter)
        self.shell_selector.bind('<Return>', self.on_terminal_start_enter)
        self.shell_selector.bind('<<ComboboxSelected>>', self._on_shell_change)

        self.new_tab_button = Button(self.terminal_options_bar, text="+ New Tab", command=self._new_terminal_tab, bg=self.button_bg, fg=self.button_fg)
        self.new_tab_button.pack(side=tk.LEFT, padx=5)

        self.close_tab_button = Button(self.terminal_options_bar, text="x Tab", command=self._close_terminal_tab, bg=self.button_bg, fg=self.button_fg)
        self.close_tab_button.pack(side=tk.LEFT, padx=5)

        self.cpp_run_button = Button(self.terminal_options_bar, text="Compile & Run C++", command=self.compile_and_run_cpp, bg=self.button_bg, fg=self.button_fg)
        self.cpp_run_button.pack(side=tk.LEFT, padx=5)
        self.cpp_run_button.bind('<Return>', lambda e: self.compile_and_run_cpp())

        # Notebook holds one tab per bash session
        self._term_notebook = ttk.Notebook(self.terminal_frame)
        self._term_notebook.pack(expand=True, fill='both', padx=5, pady=5)
        self._terminal_tabs = []
        self._new_terminal_tab()  # create the first tab

        # Rechtsklick auf Tab-Header → Schließen-Menü
        self._term_notebook.bind('<Button-3>', self._on_notebook_tab_rightclick)

        # Right-click context menu (shared; targets the active tab's widgets via bindings)
        try:
            self.term_menu = tk.Menu(self.root, tearoff=0)
            self.term_menu.add_command(label="Copy", command=self._terminal_copy)
            self.term_menu.add_command(label="Select All", command=self._terminal_select_all)
        except Exception:
            pass

        self.root.after(50, self.adjust_terminal_height)
        self.root.bind('<Configure>', self._on_root_configure)
        # F2 = push-to-talk, F3 = toggle TTS speaker
        self.root.bind('<F2>', lambda e: self._voice_push_to_talk())
        self.root.bind('<F3>', lambda e: self._voice_toggle_tts())

    # ------------------------------------------------------------------ #
    #  Multi-tab terminal helpers                                         #
    # ------------------------------------------------------------------ #

    def _active_terminal_tab(self):
        """Return the dict for the currently selected notebook tab, or None."""
        if not getattr(self, '_terminal_tabs', None):
            return None
        try:
            current = self._term_notebook.select()
            for tab in self._terminal_tabs:
                if str(tab['frame']) == current:
                    return tab
        except Exception:
            pass
        return self._terminal_tabs[0] if self._terminal_tabs else None

    @property
    def terminal_text(self):
        tab = self._active_terminal_tab()
        return tab['text'] if tab else None

    @property
    def terminal_input(self):
        tab = self._active_terminal_tab()
        return tab['input'] if tab else None

    @property
    def term_connector(self):
        tab = self._active_terminal_tab()
        return tab['connector'] if tab else None

    @term_connector.setter
    def term_connector(self, value):
        tab = self._active_terminal_tab()
        if tab is not None:
            tab['connector'] = value

    def _new_terminal_tab(self):
        """Create a new bash tab in the terminal notebook."""
        idx = len(self._terminal_tabs) + 1
        tab_frame = Frame(self._term_notebook, bg=self.secondary_color)

        text = scrolledtext.ScrolledText(tab_frame, wrap=tk.WORD, height=12,
                                         bg=self.entry_bg, fg=self.fg_color,
                                         insertbackground=self.fg_color)
        text.pack(expand=True, fill='both', padx=5, pady=5)
        text.configure(state='normal')

        inp = scrolledtext.ScrolledText(tab_frame, height=4, wrap=tk.NONE,
                                        bg=self.entry_bg, fg=self.fg_color,
                                        insertbackground=self.fg_color)
        inp.pack(fill=tk.X, padx=5, pady=(0, 5))

        tab = {'frame': tab_frame, 'text': text, 'input': inp, 'connector': None}
        self._terminal_tabs.append(tab)
        self._term_notebook.add(tab_frame, text=f"bash {idx}")
        self._term_notebook.select(tab_frame)

        # Bindings — each tab has its own widgets so bind directly
        inp.bind('<Shift-Return>', lambda e: inp.insert(tk.INSERT, '\n'))
        inp.bind('<Return>', self._on_terminal_enter)
        inp.bind('<Up>', self._term_history_up)
        inp.bind('<Down>', self._term_history_down)
        inp.bind('<Control-Shift-v>', lambda e: inp.event_generate('<<Paste>>'))
        inp.bind('<Control-Shift-V>', lambda e: inp.event_generate('<<Paste>>'))
        inp.bind('<Control-Shift-c>', lambda e: inp.event_generate('<<Copy>>'))
        inp.bind('<Control-Shift-C>', lambda e: inp.event_generate('<<Copy>>'))
        text.bind('<1>', lambda e: text.focus_set())
        text.bind('<Key>', self._terminal_text_key)
        try:
            text.bind('<Button-3>', self._show_terminal_menu)
            inp.bind('<Button-3>', self._show_terminal_menu)
            text.bind('<Button-2>', self._show_terminal_menu)
            inp.bind('<Button-2>', self._show_terminal_menu)
        except Exception:
            pass

        try:
            inp.focus_set()
        except Exception:
            pass

        # Auto-start bash in the new tab
        self.start_terminal()

    def _close_terminal_tab(self, tab_frame=None):
        """Close a specific terminal tab (or the active one if tab_frame is None).
        Stops its shell connector, cleans up references, keeps at least one tab."""
        if tab_frame is None:
            active = self._active_terminal_tab()
            if active is None:
                return
            tab_frame = active['frame']

        tab = next((t for t in self._terminal_tabs if t['frame'] is tab_frame), None)
        if tab is None:
            return

        # Stop the shell connector for this tab
        try:
            if tab.get('connector'):
                tab['connector'].stop()
        except Exception:
            pass

        # If this tab was holding the model-server log stream, detach it
        if getattr(self, '_model_log_text_widget', None) is tab.get('text'):
            self._model_log_text_widget = None

        self._terminal_tabs.remove(tab)

        try:
            self._term_notebook.forget(tab_frame)
            tab_frame.destroy()
        except Exception:
            pass

        # Always keep at least one tab open
        if not self._terminal_tabs:
            self._new_terminal_tab()

    def _on_notebook_tab_rightclick(self, event):
        """Show a close menu when right-clicking on a tab header strip."""
        try:
            tab_idx = self._term_notebook.index(f"@{event.x},{event.y}")
            tab_frame_name = self._term_notebook.tabs()[tab_idx]
            target_frame = None
            for tab in self._terminal_tabs:
                if str(tab['frame']) == tab_frame_name:
                    target_frame = tab['frame']
                    break
            if target_frame is not None:
                menu = tk.Menu(self.root, tearoff=0)
                menu.add_command(
                    label="Tab schliessen",
                    command=lambda f=target_frame: self._close_terminal_tab(f),
                )
                menu.tk_popup(event.x_root, event.y_root)
        except Exception:
            pass

    def _on_root_configure(self, event):
        # debounce repeated Configure events
        try:
            if hasattr(self, '_adjust_after_id') and self._adjust_after_id:
                self.root.after_cancel(self._adjust_after_id)
        except Exception:
            pass
        self._adjust_after_id = self.root.after(200, self.adjust_terminal_height)

    def open_folder(self):
        folder_selected = filedialog.askdirectory()
        if folder_selected:
            self.path_var.set(folder_selected)
            self.update_file_tree(folder_selected)

    def update_file_tree(self, folder_path):
        for i in self.file_tree.get_children():
            self.file_tree.delete(i)
        self._insert_tree_node('', folder_path, os.path.basename(folder_path))
        # Start auto-refresh watcher for the new folder
        self._start_explorer_watcher(folder_path)

    def refresh_file_tree(self):
        """Refresh the explorer tree without losing expanded state."""
        folder_path = self.path_var.get()
        if not folder_path or not os.path.isdir(folder_path):
            return
        # Remember which nodes are expanded
        expanded = set()
        def _collect_expanded(node=''):
            for child in self.file_tree.get_children(node):
                if self.file_tree.item(child, 'open'):
                    expanded.add(child)
                _collect_expanded(child)
        _collect_expanded()
        # Rebuild the tree
        for i in self.file_tree.get_children():
            self.file_tree.delete(i)
        self._insert_tree_node('', folder_path, os.path.basename(folder_path))
        # Re-expand previously expanded nodes
        def _re_expand(node=''):
            for child in self.file_tree.get_children(node):
                if child in expanded:
                    # Remove dummy and populate real children
                    children = self.file_tree.get_children(child)
                    if len(children) == 1 and self.file_tree.item(children[0], 'text') == '':
                        self.file_tree.delete(children[0])
                        try:
                            entries = sorted(os.scandir(child), key=lambda e: (not e.is_dir(), e.name.lower()))
                            for entry in entries:
                                self._insert_tree_node(child, entry.path, entry.name)
                        except PermissionError:
                            pass
                    self.file_tree.item(child, open=True)
                _re_expand(child)
        _re_expand()

    def _start_explorer_watcher(self, folder_path):
        """Start a background thread that polls the folder and refreshes if changed."""
        # Stop any existing watcher
        self._explorer_watcher_stop = getattr(self, '_explorer_watcher_stop', None)
        if self._explorer_watcher_stop:
            self._explorer_watcher_stop.set()
        self._explorer_watcher_stop = threading.Event()
        stop_event = self._explorer_watcher_stop

        def _watch():
            last_snapshot = None
            while not stop_event.is_set():
                try:
                    # Snapshot: set of (path, mtime) for all items in folder
                    snapshot = frozenset(
                        (e.path, e.stat().st_mtime)
                        for e in os.scandir(folder_path)
                    )
                    if last_snapshot is not None and snapshot != last_snapshot:
                        try:
                            self.root.after(0, self.refresh_file_tree)
                        except Exception:
                            pass
                    last_snapshot = snapshot
                except Exception:
                    pass
                stop_event.wait(2.0)  # Poll every 2 seconds

        t = threading.Thread(target=_watch, daemon=True)
        t.start()

    def _insert_tree_node(self, parent, path, display_name):
        node = self.file_tree.insert(parent, 'end', iid=path, text=display_name, open=False)
        if os.path.isdir(path):
            # Insert a dummy child so the expand arrow appears
            self.file_tree.insert(node, 'end', iid=path + '/__dummy__', text='')

    def _on_tree_expand(self, event):
        node = self.file_tree.focus()
        # Remove dummy child if present
        children = self.file_tree.get_children(node)
        if len(children) == 1 and self.file_tree.item(children[0], 'text') == '':
            self.file_tree.delete(children[0])
            # Populate real children
            try:
                entries = sorted(os.scandir(node), key=lambda e: (not e.is_dir(), e.name.lower()))
                for entry in entries:
                    self._insert_tree_node(node, entry.path, entry.name)
            except PermissionError:
                pass

    def refresh_tree_node(self, dir_path: str):
        """Refresh a directory node in the explorer after the agent creates/writes files.

        - If the node is already expanded, its children are updated in-place.
        - If the node is not yet in the tree but is under the open root, it is
          added to its parent (which must already be expanded).
        - Called from ide_agent via root.after(0, ...) so it always runs on the
          main thread.
        """
        try:
            dir_path = os.path.normpath(dir_path)

            # --- node not yet in tree: try to add it to its parent -----------
            if not self.file_tree.exists(dir_path):
                parent = os.path.dirname(dir_path)
                if self.file_tree.exists(parent):
                    children = self.file_tree.get_children(parent)
                    # only insert if parent is already expanded (no dummy child)
                    is_expanded = not (
                        len(children) == 1 and
                        self.file_tree.item(children[0], 'text') == ''
                    )
                    if is_expanded:
                        self._insert_tree_node(parent, dir_path, os.path.basename(dir_path))
                return

            children = self.file_tree.get_children(dir_path)

            # Node has only the dummy placeholder → not expanded yet, nothing to do
            if len(children) == 1 and self.file_tree.item(children[0], 'text') == '':
                return

            # Node is expanded → sync its children with what is on disk
            try:
                entries = sorted(os.scandir(dir_path), key=lambda e: (not e.is_dir(), e.name.lower()))
            except Exception:
                return

            disk_paths = {os.path.normpath(e.path) for e in entries}
            current_children = set(self.file_tree.get_children(dir_path))

            # Remove stale entries
            for child in list(current_children):
                if child not in disk_paths:
                    try:
                        self.file_tree.delete(child)
                    except Exception:
                        pass

            # Add new entries
            current_children = set(self.file_tree.get_children(dir_path))
            for entry in entries:
                ep = os.path.normpath(entry.path)
                if ep not in current_children:
                    self._insert_tree_node(dir_path, entry.path, entry.name)
        except Exception as e:
            print(f"[refresh_tree_node] {e}")

    # ------------------------------------------------------------------ #
    #  Explorer right-click context menu                                   #
    # ------------------------------------------------------------------ #

    def _show_explorer_menu(self, event):
        """Build and show a context menu for the clicked item in the file tree."""
        # Select the item under the cursor first
        item = self.file_tree.identify_row(event.y)
        if item:
            self.file_tree.selection_set(item)
        path = item if item else None
        is_file = path and os.path.isfile(path)
        is_dir  = path and os.path.isdir(path)

        menu = tk.Menu(self.root, tearoff=0,
                       bg=self.secondary_color, fg=self.fg_color,
                       activebackground=self.button_bg, activeforeground=self.button_fg)

        if is_file:
            menu.add_command(label="Im Editor öffnen",
                             command=lambda: self._explorer_open(path))
            menu.add_separator()
            menu.add_command(label="Umbenennen",
                             command=lambda: self._explorer_rename(path))
            menu.add_command(label="Kopieren nach…",
                             command=lambda: self._explorer_copy(path))
            menu.add_command(label="Löschen",
                             command=lambda: self._explorer_delete(path))
            menu.add_separator()
            menu.add_command(label="Pfad kopieren",
                             command=lambda: self._explorer_copy_path(path))
            menu.add_command(label="Diff (vs. Backup)",
                             command=lambda: self._explorer_diff(path))
        elif is_dir:
            menu.add_command(label="Neue Datei hier",
                             command=lambda: self._explorer_new_file(path))
            menu.add_command(label="Neuer Ordner hier",
                             command=lambda: self._explorer_new_folder(path))
            menu.add_separator()
            menu.add_command(label="Umbenennen",
                             command=lambda: self._explorer_rename(path))
            menu.add_command(label="Löschen",
                             command=lambda: self._explorer_delete(path))
            menu.add_separator()
            menu.add_command(label="Pfad kopieren",
                             command=lambda: self._explorer_copy_path(path))
            menu.add_command(label="Im Terminal öffnen",
                             command=lambda: self._explorer_open_terminal(path))
        else:
            menu.add_command(label="Neue Datei",
                             command=lambda: self._explorer_new_file(self.path_var.get()))
            menu.add_command(label="Neuer Ordner",
                             command=lambda: self._explorer_new_folder(self.path_var.get()))

        menu.tk_popup(event.x_root, event.y_root)
        try:
            menu.grab_release()
        except Exception:
            pass

    def _explorer_open(self, path):
        if os.path.isfile(path):
            try:
                self._open_in_editor_tab(path)
            except Exception as e:
                messagebox.showerror("Öffnen", str(e))

    def _explorer_rename(self, path):
        old_name = os.path.basename(path)
        new_name = simpledialog.askstring("Umbenennen", "Neuer Name:", initialvalue=old_name)
        if not new_name or new_name == old_name:
            return
        new_path = os.path.join(os.path.dirname(path), new_name)
        try:
            os.rename(path, new_path)
            if self._current_file_path == path:
                self._current_file_path = new_path
            self.refresh_tree_node(os.path.dirname(path))
        except Exception as e:
            messagebox.showerror("Umbenennen", str(e))

    def _explorer_copy(self, path):
        dest_dir = filedialog.askdirectory(title="Kopieren nach…")
        if not dest_dir:
            return
        dest = os.path.join(dest_dir, os.path.basename(path))
        try:
            if os.path.isdir(path):
                shutil.copytree(path, dest)
            else:
                shutil.copy2(path, dest)
            self.refresh_tree_node(dest_dir)
        except Exception as e:
            messagebox.showerror("Kopieren", str(e))

    def _explorer_delete(self, path):
        name = os.path.basename(path)
        kind = "Ordner" if os.path.isdir(path) else "Datei"
        if not messagebox.askyesno("Löschen",
                                   f"{kind} '{name}' wirklich löschen?\nDies kann nicht rückgängig gemacht werden."):
            return
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            if self._current_file_path == path:
                self._current_file_path = None
                self.editor_text.delete('1.0', tk.END)
                self.editor_label.config(text="Workspace")
            self.refresh_tree_node(os.path.dirname(path))
        except Exception as e:
            messagebox.showerror("Löschen", str(e))

    def _explorer_copy_path(self, path):
        self.root.clipboard_clear()
        self.root.clipboard_append(path)

    def _explorer_diff(self, path):
        """Open diff for a specific file (not just the active editor file)."""
        self._current_file_path = path
        self._show_diff()

    def _explorer_new_file(self, dir_path):
        name = simpledialog.askstring("Neue Datei", "Dateiname:", initialvalue="neue_datei.py")
        if not name:
            return
        new_path = os.path.join(dir_path, name)
        try:
            open(new_path, 'w').close()
            self.refresh_tree_node(dir_path)
            self._open_in_editor_tab(new_path)
        except Exception as e:
            messagebox.showerror("Neue Datei", str(e))

    def _explorer_new_folder(self, dir_path):
        name = simpledialog.askstring("Neuer Ordner", "Ordnername:")
        if not name:
            return
        new_path = os.path.join(dir_path, name)
        try:
            os.makedirs(new_path, exist_ok=True)
            self.refresh_tree_node(dir_path)
        except Exception as e:
            messagebox.showerror("Neuer Ordner", str(e))

    def _explorer_open_terminal(self, dir_path):
        """cd into the directory in the active terminal tab."""
        try:
            tc = self.term_connector
            if tc:
                tc.write(f"cd '{dir_path}'\n")
            else:
                self._append_terminal_text(f"cd '{dir_path}'\n")
        except Exception as e:
            self._append_terminal_text(f"Terminal-Fehler: {e}\n")

    def _set_open_file(self, path):
        """Update _current_file_path, the active tab's stored path, toolbar label, and tab title."""
        self._current_file_path = path
        tab = self._active_editor_tab()
        if tab is not None:
            tab['path'] = path
            title = os.path.basename(path) if path else 'Neu'
            try:
                self._workspace_notebook.tab(tab['frame'], text=title)
            except Exception:
                pass
        try:
            label = os.path.basename(path) if path else "(keine Datei geöffnet)"
            self.open_file_label_var.set(label)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    #  Workspace multi-tab editor                                          #
    # ------------------------------------------------------------------ #

    @property
    def editor_text(self):
        """Always return the active tab's ScrolledText widget."""
        tab = self._active_editor_tab()
        return tab['text'] if tab else None

    def _active_editor_tab(self):
        if not getattr(self, '_workspace_tabs', None):
            return None
        try:
            current = self._workspace_notebook.select()
            for tab in self._workspace_tabs:
                if str(tab['frame']) == current:
                    return tab
        except Exception:
            pass
        return self._workspace_tabs[0] if self._workspace_tabs else None

    def _new_editor_tab(self, path=None, content=''):
        """Create a new editor tab. If path is given the file is loaded from disk."""
        if path and os.path.isfile(path) and not content:
            try:
                content = open(path, encoding='utf-8', errors='replace').read()
            except Exception:
                pass

        frame = Frame(self._workspace_notebook, bg=self.secondary_color)
        text = scrolledtext.ScrolledText(
            frame, wrap=tk.WORD,
            bg=self.entry_bg, fg=self.fg_color,
            insertbackground=self.fg_color,
            undo=True, maxundo=-1,
        )
        text.pack(expand=True, fill='both')
        if content:
            text.insert('1.0', content)
        text.bind('<Control-s>',       lambda e: self.save_file()    or 'break')
        text.bind('<Control-Shift-s>', lambda e: self.save_file_as() or 'break')
        text.bind('<Control-Shift-S>', lambda e: self.save_file_as() or 'break')

        title = os.path.basename(path) if path else 'Neu'
        tab   = {'frame': frame, 'text': text, 'path': path}
        self._workspace_tabs.append(tab)
        self._workspace_notebook.add(frame, text=title)
        self._workspace_notebook.select(frame)
        self._current_file_path = path
        try:
            self.open_file_label_var.set(title if path else '(keine Datei geöffnet)')
        except Exception:
            pass
        return tab

    def _open_in_editor_tab(self, path):
        """Open a file in the workspace.
        If the file is already open in a tab, switch to it.
        Otherwise create a new tab.
        """
        path = os.path.normpath(path)
        # Check if already open
        for tab in self._workspace_tabs:
            if tab.get('path') and os.path.normpath(tab['path']) == path:
                self._workspace_notebook.select(tab['frame'])
                self._current_file_path = path
                try:
                    self.open_file_label_var.set(os.path.basename(path))
                except Exception:
                    pass
                return
        # Auto-close oldest tab if limit exceeded (keep at most MAX_EDITOR_TABS)
        while len(self._workspace_tabs) >= MAX_EDITOR_TABS:
            oldest = self._workspace_tabs[0]
            self._close_editor_tab(oldest['frame'])

        # Open in new tab
        self._new_editor_tab(path=path)

    def _close_editor_tab(self, tab_frame=None):
        """Close a workspace tab. Always keeps at least one tab open."""
        if tab_frame is None:
            active = self._active_editor_tab()
            if active is None:
                return
            tab_frame = active['frame']

        tab = next((t for t in self._workspace_tabs if t['frame'] is tab_frame), None)
        if tab is None:
            return

        self._workspace_tabs.remove(tab)
        try:
            self._workspace_notebook.forget(tab_frame)
            tab_frame.destroy()
        except Exception:
            pass

        if not self._workspace_tabs:
            self._new_editor_tab()
        else:
            active = self._active_editor_tab()
            self._current_file_path = active['path'] if active else None
            try:
                name = os.path.basename(active['path']) if active and active['path'] else '(keine Datei geöffnet)'
                self.open_file_label_var.set(name)
            except Exception:
                pass

    def _on_workspace_tab_changed(self, event=None):
        """Sync _current_file_path and toolbar label when switching tabs."""
        tab = self._active_editor_tab()
        if tab:
            self._current_file_path = tab.get('path')
            try:
                name = os.path.basename(tab['path']) if tab.get('path') else '(keine Datei geöffnet)'
                self.open_file_label_var.set(name)
            except Exception:
                pass

    def _on_workspace_tab_rightclick(self, event):
        """Right-click on a workspace tab header → close menu."""
        try:
            tab_idx       = self._workspace_notebook.index(f"@{event.x},{event.y}")
            tab_frame_name = self._workspace_notebook.tabs()[tab_idx]
            target_frame  = None
            for tab in self._workspace_tabs:
                if str(tab['frame']) == tab_frame_name:
                    target_frame = tab['frame']
                    break
            if target_frame is None:
                return
            menu = tk.Menu(self.root, tearoff=0,
                           bg=self.secondary_color, fg=self.fg_color,
                           activebackground=self.button_bg, activeforeground=self.button_fg)
            menu.add_command(label="Tab schließen",
                             command=lambda f=target_frame: self._close_editor_tab(f))
            menu.add_command(label="Alle anderen schließen",
                             command=lambda f=target_frame: self._close_all_but(f))
            menu.tk_popup(event.x_root, event.y_root)
            try:
                menu.grab_release()
            except Exception:
                pass
        except Exception:
            pass

    def _close_all_but(self, keep_frame):
        """Close all workspace tabs except the one given."""
        to_close = [t['frame'] for t in self._workspace_tabs if t['frame'] is not keep_frame]
        for frame in to_close:
            self._close_editor_tab(frame)

    def on_file_select(self, event):
        # Single click → open in a new tab (or switch to existing tab for this file)
        selection = self.file_tree.selection()
        if not selection:
            return
        file_path = selection[0]
        if not os.path.isfile(file_path):
            return
        try:
            self._open_in_editor_tab(file_path)
        except Exception as e:
            messagebox.showerror("Open File", f"Failed to open file: {e}")

    def on_file_double_click(self, event):
        # Identify the row under the cursor and open it
        item = self.file_tree.identify_row(event.y)
        if not item:
            return
        self.file_tree.selection_set(item)
        self.on_file_select(None)

    def on_start_enter(self, event):
        self.start_session()
        return "break"

    def on_terminal_start_enter(self, event):
        self.start_terminal()
        return "break"

    def _load_system_prompts(self):
        prompts_path = os.path.join(os.path.dirname(__file__), 'system_prompts.json')
        if os.path.exists(prompts_path):
            try:
                with open(prompts_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading system prompts: {e}")
        return {}

    # ------------------------------------------------------------------ #
    #  API key persistence                                                 #
    # ------------------------------------------------------------------ #

    _KEYS_FILE = os.path.join(os.path.expanduser('~'), '.astraeus_api_keys.json')

    def _load_api_keys(self):
        """Read saved API keys from disk and inject them into os.environ."""
        try:
            if os.path.exists(self._KEYS_FILE):
                with open(self._KEYS_FILE, 'r') as f:
                    keys = json.load(f)
                for var, val in keys.items():
                    if val:
                        os.environ[var] = val
        except Exception as e:
            print(f"[API keys] Could not load keys: {e}")

    def _save_api_keys(self, keys: dict):
        """Write API keys dict to disk with restricted permissions."""
        try:
            with open(self._KEYS_FILE, 'w') as f:
                json.dump(keys, f, indent=2)
            os.chmod(self._KEYS_FILE, 0o600)   # owner read/write only
        except Exception as e:
            messagebox.showerror("API Keys", f"Konnte Keys nicht speichern: {e}")

    def _edit_api_keys(self):
        """Open a dialog to enter / update cloud API keys."""
        win = tk.Toplevel(self.root)
        win.title("API Keys")
        win.configure(bg=self.bg_color)
        win.resizable(False, False)
        win.grab_set()

        # Read current saved keys (or env fallback)
        def _current(var):
            try:
                if os.path.exists(self._KEYS_FILE):
                    with open(self._KEYS_FILE, 'r') as f:
                        return json.load(f).get(var, '') or ''
            except Exception:
                pass
            return os.environ.get(var, '')

        pad = {'padx': 10, 'pady': 5}

        Label(win, text="Anthropic API Key  (Claude)", bg=self.bg_color, fg=self.fg_color).grid(row=0, column=0, sticky='w', **pad)
        anthropic_var = tk.StringVar(value=_current('ANTHROPIC_API_KEY'))
        anthropic_entry = Entry(win, textvariable=anthropic_var, width=55, show='*', bg=self.entry_bg, fg=self.fg_color, insertbackground=self.fg_color)
        anthropic_entry.grid(row=0, column=1, **pad)

        Label(win, text="Mistral API Key  (Mistral AI)", bg=self.bg_color, fg=self.fg_color).grid(row=1, column=0, sticky='w', **pad)
        mistral_var = tk.StringVar(value=_current('MISTRAL_API_KEY'))
        mistral_entry = Entry(win, textvariable=mistral_var, width=55, show='*', bg=self.entry_bg, fg=self.fg_color, insertbackground=self.fg_color)
        mistral_entry.grid(row=1, column=1, **pad)

        # Toggle visibility
        show_var = tk.BooleanVar(value=False)
        def _toggle():
            char = '' if show_var.get() else '*'
            anthropic_entry.config(show=char)
            mistral_entry.config(show=char)
        Checkbutton = tk.Checkbutton
        Checkbutton(win, text="Keys anzeigen", variable=show_var, command=_toggle,
                    bg=self.bg_color, fg=self.fg_color, selectcolor=self.entry_bg,
                    activebackground=self.bg_color).grid(row=2, column=1, sticky='w', **pad)

        def _save():
            keys = {
                'ANTHROPIC_API_KEY': anthropic_var.get().strip(),
                'MISTRAL_API_KEY':   mistral_var.get().strip(),
            }
            self._save_api_keys(keys)
            # Inject immediately into the running process
            for var, val in keys.items():
                if val:
                    os.environ[var] = val
                elif var in os.environ:
                    del os.environ[var]
            win.destroy()
            messagebox.showinfo("API Keys", "Keys gespeichert und aktiv.")

        btn_frame = Frame(win, bg=self.bg_color)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=10)
        Button(btn_frame, text="Speichern", command=_save,
               bg=self.button_bg, fg=self.button_fg, width=12).pack(side=tk.LEFT, padx=8)
        Button(btn_frame, text="Abbrechen", command=win.destroy,
               bg=self.button_bg, fg=self.button_fg, width=12).pack(side=tk.LEFT, padx=8)

    def start_session(self):
        # Only print the start message once per chat session; repeated presses won't duplicate it
        if getattr(self, '_chat_started', False):
            return
        model = self.model_var.get()
        self.chat_display.configure(state='normal')
        self.chat_display.insert(tk.END, f"Started chat with model: {model}\n", 'system')
        self.chat_display.see(tk.END)
        self.chat_display.configure(state='disabled')
        self._chat_started = True

    def _on_model_selected(self, event=None):
        # Reset chat-started flag when user selects a different model so Start Chat
        # will print again for a new session if desired.
        try:
            self._chat_started = False
        except Exception:
            pass
        # Auto-start the selected model server
        try:
            self.start_model_server()
        except Exception as e:
            self._append_terminal_text(f"Auto-start failed: {e}\n")

    def _edit_model_template(self):
        # Open a dialog to paste or edit the model's chat template (Jinja2)
        model_name = self.model_var.get()
        if not self.app_config or model_name not in getattr(self.app_config, 'models', {}):
            messagebox.showwarning("Edit Template", f"No config for model {model_name}")
            return
        cfg = self.app_config.models[model_name]
        initial = getattr(cfg, 'chat_template', '') or ''
        # multi-line input dialog
        txt = simpledialog.askstring("Edit Chat Template", "Paste tokenizer.chat_template (Jinja2):", initialvalue=initial)
        if txt is None:
            return
        try:
            cfg.chat_template = txt
            self._append_terminal_text(f"Saved chat template for {model_name}\n")
        except Exception as e:
            self._append_terminal_text(f"Failed to save template: {e}\n")

    def _render_with_template(self, cfg, messages: list) -> str:
        # Render messages into the model's chat template using Jinja2 if available.
        tpl = getattr(cfg, 'chat_template', None)
        if not tpl:
            # default: concatenate messages
            return "\n".join([m.get('content', '') for m in messages])
        if not jinja2:
            # Jinja not installed; fallback
            return "\n".join([m.get('content', '') for m in messages])
        try:
            template = jinja2.Template(tpl)
            rendered = template.render(messages=messages, bos_token="", eos_token="")
            return rendered
        except Exception:
            return "\n".join([m.get('content', '') for m in messages])

    def _show_terminal_menu(self, event):
        try:
            # remember which widget requested the menu
            self._term_menu_widget = event.widget
            self.term_menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                self.term_menu.grab_release()
            except Exception:
                pass

    def _terminal_copy(self):
        w = getattr(self, '_term_menu_widget', None)
        if not w:
            return
        try:
            txt = w.get('sel.first', 'sel.last')
            if txt:
                self.root.clipboard_clear()
                self.root.clipboard_append(txt)
        except Exception:
            pass

    def _terminal_select_all(self):
        w = getattr(self, '_term_menu_widget', None)
        if not w:
            return
        try:
            w.tag_add('sel', '1.0', 'end')
        except Exception:
            pass

    def _start_chat_and_ensure_model(self):
        # (removed) helper previously auto-started model server; kept for history but no-op now
        self.start_session()

    def start_terminal(self):
        shell = self.shell_var.get()
        self.terminal_text.configure(state='normal')
        self.terminal_text.insert(tk.END, f"Started terminal: {shell}\n")
        self.terminal_text.configure(state='disabled')
        self.terminal_text.see(tk.END)
        try:
            # place keyboard focus into the terminal input when the shell starts
            self.terminal_input.focus_set()
        except Exception:
            pass

        # stop existing connector if any
        try:
            if getattr(self, 'term_connector', None):
                try:
                    self.term_connector.stop()
                except Exception:
                    pass
                self.term_connector = None
        except Exception:
            pass

        # Always use local Bash on Linux
        cmd = ["/bin/bash", "-i"]

        # validate that the requested shell executable exists before attempting to start
        cmd_exec = cmd[0] if cmd else None
        try:
            found = False
            if cmd_exec:
                if os.path.isabs(cmd_exec):
                    found = os.path.exists(cmd_exec)
                else:
                    found = shutil.which(cmd_exec) is not None
            if not found:
                self._append_terminal_text(f"Shell executable not found: {cmd_exec}\n")
                return
        except Exception:
            # if validation itself fails, continue and let the connector report the error
            pass

        # create and start connector; capture the active tab's text widget so
        # background output always lands in the correct tab even after switching.
        try:
            active_tab = self._active_terminal_tab()
            text_widget = active_tab['text'] if active_tab else None

            def _tab_appender(text, _widget=text_widget):
                clean = _strip_ansi(text)
                if not clean:
                    return
                def _do():
                    try:
                        _widget.configure(state='normal')
                        _widget.insert(tk.END, clean)
                        _widget.see(tk.END)
                    except Exception:
                        pass
                try:
                    self.root.after(0, _do)
                except Exception:
                    pass

            self.term_connector = TerminalConnector()
            self.term_connector.start(cmd, _tab_appender)
        except Exception as e:
            self._append_terminal_text(f"Failed to start connector: {e}\n")

    def send_message(self):
        message = self.chat_input.get(1.0, tk.END).strip()
        if message:
            self.chat_display.configure(state='normal')
            self.chat_display.insert(tk.END, "You: ", 'you')
            self.chat_display.insert(tk.END, f"{message}\n", 'you_text')
            self.chat_display.see(tk.END)
            self.chat_input.delete(1.0, tk.END)

            # Capture the active model name NOW so the header always matches
            # whichever model was selected when Send was pressed.
            active_model = self.model_var.get()

            def get_and_display():
                # Write the model header first so intermediate steps (streamed
                # from inside process_message via after(0,...)) appear under it.
                def _write_header():
                    self.chat_display.configure(state='normal')
                    self.chat_display.insert(tk.END, f"{active_model}: ", 'ai')
                    self.chat_display.see(tk.END)
                    self.chat_display.configure(state='disabled')
                self.root.after(0, _write_header)

                try:
                    agent = getattr(self, 'ide_agent', None)
                    if agent:
                        response = agent.process_message(message)
                    else:
                        response = self.get_response(message)
                except Exception as e:
                    response = f"[Interner Fehler: {e}]"

                if not response or not response.strip():
                    response = f"[Keine Antwort von {active_model} — ist der Server gestartet?]"

                def _write_final():
                    self.chat_display.configure(state='normal')
                    self.chat_display.insert(tk.END, f"{response}\n", 'ai_text')
                    self.chat_display.see(tk.END)
                    self.chat_display.configure(state='disabled')
                    # Auto-speak if TTS is on (skip server connection errors)
                    if self._voice_tts_on and self._voice_engine and self._voice_engine.is_ready:
                        if not response.startswith(("Error:", "[Interner Fehler:", "[Keine Antwort von")):
                            if "Is the server for" not in response:
                                self._voice_engine.speak(_strip_for_tts(response))
                self.root.after(0, _write_final)

            threading.Thread(target=get_and_display, daemon=True).start()

    def get_response(self, message):
        # Dynamically call the correct model based on selection
        model_name = self.model_var.get()
        return self._call_model_api(model_name, message)

    def _call_model_api(self, model_name, message):
        # Generic API caller that works for any model in config.py
        cfg = None
        if self.app_config and model_name in getattr(self.app_config, 'models', {}):
            cfg = self.app_config.models[model_name]

        # Load system prompt from JSON based on model name
        system_content = self.system_prompts.get(model_name, "You are a helpful AI assistant.")
        messages = [
            {'role': 'system', 'content': system_content},
            {'role': 'user', 'content': message}
        ]

        # Route cloud models before touching host/port
        endpoint_type = getattr(cfg, 'endpoint_type', 'chat')
        if endpoint_type == "anthropic":
            return self._call_anthropic_api(cfg, messages)
        if endpoint_type == "mistral":
            return self._call_mistral_api(cfg, messages)

        prompt = self._render_with_template(cfg, messages) if cfg else message

        # Connection details from config
        host = cfg.host if cfg else '127.0.0.1'
        port = cfg.port if cfg else 8081
        base = f"http://{host}:{port}"
        nm = self.network_manager
        tokens_key = "n_predict" if getattr(cfg, 'use_n_predict', False) else "max_tokens"

        # Try preferred endpoint first, then fallback to others
        if endpoint_type == "legacy":
            # Use n_predict (llama.cpp native) not max_tokens for completions endpoint
            try:
                url = base + "/v1/completions"
                payload = {"prompt": prompt, "n_predict": -1}
                resp = nm.post(url, json=payload, timeout=600)
                data = resp.json()
                if 'choices' in data:
                    return data['choices'][0]['text']
            except Exception:
                pass
            # Fallback to chat completions
            try:
                url = base + "/v1/chat/completions"
                payload = {"model": model_name, "messages": messages, tokens_key: -1}
                resp = nm.post(url, json=payload, timeout=600)
                data = resp.json()
                if 'choices' in data:
                    return data['choices'][0]['message']['content']
            except Exception:
                pass
        else:
            # Try chat completions first (default)
            try:
                url = base + "/v1/chat/completions"
                payload = {"model": model_name, "messages": messages, tokens_key: -1}
                resp = nm.post(url, json=payload, timeout=600)
                data = resp.json()
                if 'choices' in data:
                    return data['choices'][0]['message']['content']
            except Exception:
                pass
            # Fallback to legacy completions API with rendered prompt
            try:
                url = base + "/v1/completions"
                payload = {"prompt": prompt, "n_predict": -1}
                resp = nm.post(url, json=payload, timeout=600)
                data = resp.json()
                if 'choices' in data:
                    return data['choices'][0]['text']
            except Exception:
                pass

        # Fallback to old native llama.cpp endpoint (no /v1 prefix)
        try:
            url = base + "/completion"
            payload = {"prompt": prompt}
            resp = nm.post(url, json=payload, timeout=600)
            data = resp.json()
            if 'content' in data:
                return data['content']
            return str(data)
        except Exception as e:
            return f"Error: {e}. Is the server for {model_name} running on port {port}?"

    def _call_model_api_messages(self, model_name, messages):
        """Like _call_model_api but accepts a pre-built messages list."""
        cfg = None
        if self.app_config and model_name in getattr(self.app_config, 'models', {}):
            cfg = self.app_config.models[model_name]

        endpoint_type = getattr(cfg, 'endpoint_type', 'chat')

        # Route cloud models before touching host/port (cloud has no local server)
        if endpoint_type == "anthropic":
            return self._call_anthropic_api(cfg, messages)
        if endpoint_type == "mistral":
            return self._call_mistral_api(cfg, messages)

        host = cfg.host if cfg else '127.0.0.1'
        port = cfg.port if cfg else 8081
        base = f"http://{host}:{port}"
        nm = self.network_manager
        tokens_key = "n_predict" if getattr(cfg, 'use_n_predict', False) else "max_tokens"

        if endpoint_type == "legacy":
            # Try legacy completions first
            # Use n_predict (llama.cpp native) not max_tokens for this endpoint
            prompt = self._render_with_template(cfg, messages) if cfg else messages[-1]['content']
            try:
                url = base + "/v1/completions"
                payload = {"prompt": prompt, "n_predict": -1}
                resp = nm.post(url, json=payload, timeout=600)
                data = resp.json()
                if 'choices' in data:
                    return data['choices'][0]['text']
            except Exception:
                pass
            # Fallback to chat completions (OpenAI-compatible field)
            try:
                url = base + "/v1/chat/completions"
                payload = {"model": model_name, "messages": messages, tokens_key: -1}
                resp = nm.post(url, json=payload, timeout=600)
                data = resp.json()
                if 'choices' in data:
                    return data['choices'][0]['message']['content']
            except Exception:
                pass
        else:
            # Try chat completions first (default)
            try:
                url = base + "/v1/chat/completions"
                payload = {"model": model_name, "messages": messages, tokens_key: -1}
                resp = nm.post(url, json=payload, timeout=600)
                data = resp.json()
                if 'choices' in data:
                    return data['choices'][0]['message']['content']
            except Exception:
                pass
            # Fallback: render prompt and use legacy completions
            prompt = self._render_with_template(cfg, messages) if cfg else messages[-1]['content']
            try:
                url = base + "/v1/completions"
                payload = {"prompt": prompt, "n_predict": -1}
                resp = nm.post(url, json=payload, timeout=600)
                data = resp.json()
                if 'choices' in data:
                    return data['choices'][0]['text']
            except Exception:
                pass

        # Fallback to old native llama.cpp endpoint (no /v1 prefix)
        try:
            url = base + "/completion"
            payload = {"prompt": prompt, "n_predict": -1}
            resp = nm.post(url, json=payload, timeout=600)
            data = resp.json()
            if 'content' in data:
                return data['content']
            return str(data)
        except Exception as e:
            return f"Error: {e}. Is the server for {model_name} running on port {port}?"

    def _call_anthropic_api(self, cfg, messages):
        """Call the Anthropic Messages API for Claude models."""
        import requests as _req
        api_key = os.environ.get(cfg.api_key_env, "")
        if not api_key:
            return (
                f"Error: Umgebungsvariable {cfg.api_key_env} nicht gesetzt.\n"
                f"Bitte in einem Terminal ausführen: export {cfg.api_key_env}=dein-schlüssel\n"
                f"Oder dauerhaft in ~/.bashrc / ~/.profile eintragen."
            )
        # Anthropic takes system as a top-level field, not inside messages
        system_content = ""
        chat_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system_content = msg.get("content", "")
            else:
                chat_messages.append({"role": msg["role"], "content": msg["content"]})
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": cfg.model_id,
            "max_tokens": 8192,
            "messages": chat_messages,
        }
        if system_content:
            payload["system"] = system_content
        try:
            resp = _req.post(
                f"{cfg.base_url}/v1/messages",
                headers=headers,
                json=payload,
                timeout=600,
            )
            data = resp.json()
            if "content" in data and data["content"]:
                return data["content"][0].get("text", "")
            if "error" in data:
                return f"Error: {data['error'].get('message', str(data['error']))}"
            return str(data)
        except Exception as e:
            return f"Error: {e}"

    def _call_mistral_api(self, cfg, messages):
        """Call the Mistral AI chat completions API (OpenAI-compatible)."""
        import requests as _req
        api_key = os.environ.get(cfg.api_key_env, "")
        if not api_key:
            return (
                f"Error: Umgebungsvariable {cfg.api_key_env} nicht gesetzt.\n"
                f"Bitte in einem Terminal ausführen: export {cfg.api_key_env}=dein-schlüssel\n"
                f"Oder dauerhaft in ~/.bashrc / ~/.profile eintragen."
            )
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": cfg.model_id,
            "messages": messages,
            "max_tokens": 8192,
        }
        try:
            resp = _req.post(
                f"{cfg.base_url}/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=600,
            )
            data = resp.json()
            if "choices" in data:
                return data["choices"][0]["message"]["content"]
            if "error" in data:
                err = data["error"]
                msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                return f"Error: {msg}"
            if "message" in data:
                return f"Error: {data['message']}"
            return str(data)
        except Exception as e:
            return f"Error: {e}"

    def call_astraeus(self, message):
        return self._call_model_api("AI_Assistant", message)

    def call_dolphin(self, message):
        return self._call_model_api("Dolphin", message)

    def call_devstral(self, message):
        return self._call_model_api("Devstral", message)

    def execute_command(self, command, shell="PowerShell"):
        try:
            # Execute command using local bash
            completed = subprocess.run(["bash", "-lc", command], capture_output=True, text=True, timeout=60)
            output = completed.stdout + completed.stderr
            return output
        except Exception as e:
            return f"Error executing command: {e}"

    def compile_and_run_cpp(self):
        # Determine file to compile: prefer selected file in explorer, otherwise ask to save
        selection = self.file_tree.selection()
        file_path = None
        if selection:
            selected_item = selection[0]
            file_path = selected_item if os.path.isabs(selected_item) else os.path.join(self.path_var.get(), self.file_tree.item(selected_item, 'text'))
        else:
            file_path = filedialog.asksaveasfilename(defaultextension='.cpp', filetypes=[('C++ files', '*.cpp'), ('All files', '*.*')])
            if not file_path:
                return

        # Write current editor contents to file path
        try:
            with open(file_path, 'w') as f:
                f.write(self.editor_text.get(1.0, tk.END))
        except Exception as e:
            self._append_terminal_text(f"Failed to save file: {e}\n")
            return

        # Prepare output binary path (same folder, same base name)
        base, _ = os.path.splitext(file_path)
        out_path = base
        # compile with g++
        compile_cmd = ["g++", "-std=c++17", "-O2", file_path, "-o", out_path]
        try:
            self._append_terminal_text(f"Compiling: {' '.join(compile_cmd)}\n")
            completed = subprocess.run(compile_cmd, capture_output=True, text=True, timeout=60)
            if completed.returncode != 0:
                self._append_terminal_text("Compilation failed:\n" + (completed.stdout or '') + (completed.stderr or '') + "\n")
                return
            self._append_terminal_text("Compilation succeeded. Running...\n")
            # run the produced binary
            run_cmd = [out_path] if os.path.isabs(out_path) else [out_path]
            # ensure executable path is correct
            if not os.path.isabs(run_cmd[0]) and not run_cmd[0].startswith('./'):
                run_cmd[0] = './' + run_cmd[0]
            completed_run = subprocess.run(run_cmd, capture_output=True, text=True, timeout=30)
            output = (completed_run.stdout or '') + (completed_run.stderr or '')
            self._append_terminal_text(output + "\n")
        except subprocess.TimeoutExpired:
            self._append_terminal_text("Compilation or execution timed out.\n")
        except Exception as e:
            self._append_terminal_text(f"Error during compile/run: {e}\n")

    def _stream_process_logs(self, proc):
        # Capture the pinned widget once — written at server-start time so logs
        # always go to that tab, never to whatever tab the user opens later.
        log_widget = getattr(self, '_model_log_text_widget', None)
        try:
            for raw in iter(proc.stdout.readline, b''):
                if not raw:
                    break
                try:
                    line = raw.decode(errors='ignore')
                except Exception:
                    line = str(raw)
                # Write to the tab that was active when the server was started
                if log_widget is not None:
                    clean = _strip_ansi(line)
                    if clean:
                        def _do(t=clean, w=log_widget):
                            try:
                                w.configure(state='normal')
                                w.insert(tk.END, t)
                                w.see(tk.END)
                            except Exception:
                                pass
                        try:
                            self.root.after(0, _do)
                        except Exception:
                            pass
                else:
                    self._append_terminal_text(line)
                # also append to log file if present
                try:
                    lp = getattr(self, '_model_log_file', None)
                    if lp:
                        try:
                            lp.write(line)
                            lp.flush()
                        except Exception:
                            pass
                except Exception:
                    pass
                if self._model_log_stop.is_set():
                    break
        except Exception:
            pass

    def start_model_server(self):
        # Automatically stop any previous model server and clean up processes before starting a new one.
        # This prevents the "couldnt bind socket" and VRAM leak issues.
        self.stop_model_server()
        
        model_name = self.model_var.get()
        if not self.app_config or model_name not in getattr(self.app_config, 'models', {}):
            self._append_terminal_text(f"No config for model {model_name}\n")
            return
        
        cfg = self.app_config.models[model_name]

        # Cloud models need no local server
        endpoint_type = getattr(cfg, 'endpoint_type', 'chat')
        if endpoint_type in ('anthropic', 'mistral'):
            self._append_terminal_text(f"{model_name} ist ein Cloud-Modell — kein lokaler Server nötig.\n")
            api_key_env = getattr(cfg, 'api_key_env', '')
            if api_key_env and not os.environ.get(api_key_env):
                self._append_terminal_text(
                    f"Hinweis: {api_key_env} ist nicht gesetzt.\n"
                    f"  export {api_key_env}=dein-api-schlüssel\n"
                )
            else:
                self._append_terminal_text(f"{api_key_env} gefunden — bereit.\n")
            return

        cmd = cfg.command if cfg else None
        if not cmd:
            self._append_terminal_text(f"No start command for {model_name}\n")
            return
        # decide whether to run under a shell (needed for exports, && etc.)
        use_shell = False
        shell_tokens = ["&&", "|", ";", "$", "export ", "~"]
        for t in shell_tokens:
            if t in cmd:
                use_shell = True
                break

        # prepare GUI log file
        try:
            log_path = './llama-server-gui.log'
            self._model_log_file = open(log_path, 'a', buffering=1)
            self._append_terminal_text(f"Logging model server output to {log_path}\n")
        except Exception:
            self._model_log_file = None

        # capture environment and working dir for debugging
        try:
            env = os.environ.copy()
            env_dump = '\n'.join([f"{k}={v}" for k, v in list(env.items())[:40]])
            self._append_terminal_text("Env snapshot (truncated):\n" + env_dump + "\n")
        except Exception:
            env = None

        try:
            if use_shell:
                proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, cwd=os.path.expanduser('~'))
            else:
                args = shlex.split(cmd)
                proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, cwd=os.path.expanduser('~'))
        except Exception as e:
            self._append_terminal_text(f"Failed to start server: {e}\n")
            try:
                if getattr(self, '_model_log_file', None):
                    self._model_log_file.close()
                    self._model_log_file = None
            except Exception:
                pass
            return
        self._model_proc = proc
        # Pin the log output to the tab that is active RIGHT NOW so that opening
        # new bash tabs later does not redirect the model server stream there.
        self._model_log_text_widget = self.terminal_text
        self._model_log_stop.clear()
        self._model_log_thread = threading.Thread(target=self._stream_process_logs, args=(proc,), daemon=True)
        self._model_log_thread.start()
        self._append_terminal_text(f"Started model server '{model_name}' (pid={proc.pid})\n")
        # verify server is accepting connections
        try:
            base = f"http://{cfg.host}:{cfg.port}"
            self._append_terminal_text(f"Probing server at {base} ...\n")
            import requests
            for i in range(6):
                try:
                    r = requests.get(base + '/v1/models', timeout=2)
                    if r.status_code == 200:
                        self._append_terminal_text("Server responded to /v1/models\n")
                        break
                except Exception:
                    pass
                time.sleep(0.5)
        except Exception:
            pass

    def stop_model_server(self):
        # First, attempt to kill any llama-server processes by name to ensure no lingering instances.
        import subprocess
        try:
            subprocess.run(["pkill", "-9", "llama-server"], capture_output=True)
            self._append_terminal_text("Force killed all 'llama-server' instances.\n")
        except Exception:
            pass

        if self._model_proc is None:
            self._append_terminal_text("No GUI-managed model server was tracked.\n")
            return
        
        proc = self._model_proc
        self._append_terminal_text(f"Stopping tracked model server (pid={proc.pid})...\n")
        try:
            proc.kill() # Direct kill as llama-server often ignores SIGTERM
            proc.wait(timeout=2)
        except Exception:
            pass
            
        self._model_log_stop.set()
        self._model_proc = None
        self._model_log_text_widget = None
        self._append_terminal_text("Model server shutdown complete.\n")

    def _on_terminal_enter(self, event=None):
        # read the entire input box contents, strip trailing newlines, send to shell
        try:
            cmd = self.terminal_input.get(1.0, tk.END).rstrip('\n')
        except Exception:
            return "break"
        if not cmd:
            return "break"
        # save to history
        if cmd.strip():
            self._term_history.append(cmd)
            self._term_history_idx = len(self._term_history)
        # clear input box
        try:
            self.terminal_input.delete(1.0, tk.END)
        except Exception:
            pass
        # send to connector if available, otherwise run as one-off
        if getattr(self, 'term_connector', None):
            try:
                self.term_connector.write(cmd + "\n")
            except Exception as e:
                self._append_terminal_text(f"Failed to send to shell: {e}\n")
        else:
            out = self.execute_command(cmd, shell=self.shell_var.get())
            self._append_terminal_text(out + "\n")
        return "break"

    def _terminal_reader(self):
        proc = getattr(self, 'terminal_proc', None)
        if not proc:
            return
        try:
            for line in proc.stdout:
                self._append_terminal_text(line)
        except Exception:
            pass

    def _append_terminal_text(self, text: str) -> None:
        # append text safely from background threads
        clean = _strip_ansi(text)
        if not clean:
            return
        def _append():
            self.terminal_text.configure(state='normal')
            self.terminal_text.insert(tk.END, clean)
            self.terminal_text.see(tk.END)
        try:
            self.root.after(0, _append)
        except Exception:
            pass

    def _on_shell_change(self, event=None):
        # User changed the shell selection — stop any running connector
        try:
            if getattr(self, 'term_connector', None):
                try:
                    self.term_connector.stop()
                except Exception:
                    pass
                self.term_connector = None
                self._append_terminal_text("Connector stopped due to shell change.\n")
        except Exception:
            pass

    def _term_history_up(self, event=None):
        if not self._term_history:
            return 'break'
        if self._term_history_idx > 0:
            self._term_history_idx -= 1
        try:
            self.terminal_input.delete(1.0, tk.END)
            self.terminal_input.insert(1.0, self._term_history[self._term_history_idx])
            self.terminal_input.mark_set(tk.INSERT, tk.END)
        except Exception:
            pass
        return 'break'

    def _term_history_down(self, event=None):
        if not self._term_history:
            return 'break'
        if self._term_history_idx < len(self._term_history) - 1:
            self._term_history_idx += 1
            try:
                self.terminal_input.delete(1.0, tk.END)
                self.terminal_input.insert(1.0, self._term_history[self._term_history_idx])
                self.terminal_input.mark_set(tk.INSERT, tk.END)
            except Exception:
                pass
        else:
            self._term_history_idx = len(self._term_history)
            try:
                self.terminal_input.delete(1.0, tk.END)
            except Exception:
                pass
        return 'break'

    def _terminal_text_key(self, event):
        # Forward key events from the output area to the terminal PTY so the user
        # can type directly into the terminal. The shell will echo back output
        # which will be appended by the reader thread.
        tc = getattr(self, 'term_connector', None)
        if not tc:
            return 'break'
        # Printable characters
        try:
            if event.char and ord(event.char) >= 32:
                tc.write(event.char)
                return 'break'
        except Exception:
            pass
        # Non-printable keys
        ks = event.keysym
        if ks == 'Return':
            tc.write('\n')
        elif ks == 'BackSpace':
            tc.write('\x7f')
        elif ks == 'Left':
            tc.write('\x1b[D')
        elif ks == 'Right':
            tc.write('\x1b[C')
        elif ks == 'Up':
            tc.write('\x1b[A')
        elif ks == 'Down':
            tc.write('\x1b[B')
        elif ks == 'Escape':
            tc.write('\x1b')
        elif ks == 'Delete':
            tc.write('\x1b[3~')
        elif ks == 'Tab':
            tc.write('\t')
        else:
            ctrl  = bool(event.state & 0x4)
            shift = bool(event.state & 0x1)
            k = ks.lower()
            if ctrl and shift and k == 'c':
                # Linux terminal copy: Shift+Ctrl+C
                try:
                    selected = self.terminal_text.get("sel.first", "sel.last")
                    self.root.clipboard_clear()
                    self.root.clipboard_append(selected)
                except Exception:
                    pass
                return 'break'
            elif ctrl and k == 'c':
                # Ctrl+C without Shift = SIGINT
                tc.write('\x03')
                return 'break'
            elif ctrl and shift and k == 'v':
                # Linux terminal paste: Shift+Ctrl+V
                try:
                    text = self.root.clipboard_get()
                    tc.write(text)
                except Exception:
                    pass
                return 'break'
            elif ctrl and k == 'a':
                # select all in output — let Tk handle it
                return None
        return 'break'

    # ── Voice ──────────────────────────────────────────────────────────────────

    def _init_voice(self):
        """Load voice engine and schedule manager in a background thread."""
        def _load():
            try:
                from astraeus_voice import VoiceEngine
                engine = VoiceEngine()
                ok, msg = engine.setup()
                # Always store the engine so the setup dialog can show correct info
                self._voice_engine = engine
                engine.set_state_callback(self._voice_state_update)
                if ok:
                    print(f"[Voice] {msg}")
                    self.root.after(0, lambda: self.voice_status_label.config(
                        text="Voice ready", fg="#7ed07e"))
                    # Start schedule manager now that voice is ready
                    self.root.after(0, self._init_schedule)
                else:
                    print(f"[Voice] Not ready: {msg}")
                    self.root.after(0, lambda: self.voice_status_label.config(
                        text="Voice: setup needed", fg="#f0a500"))
            except Exception as e:
                print(f"[Voice] Init error: {e}")
        threading.Thread(target=_load, daemon=True, name="voice-init").start()

    def _init_schedule(self):
        """Initialise the daily schedule (morning briefing + nightly shutdown)."""
        try:
            from astraeus_schedule import ScheduleManager

            def _ai_call(prompt: str) -> str:
                agent = getattr(self, 'ide_agent', None)
                if agent:
                    return agent.process_message(prompt)
                return self.get_response(prompt)

            self._schedule = ScheduleManager(
                voice_engine=self._voice_engine,
                ai_call=_ai_call,
                memory_search_path=str(Path.home()),
            )
            self._schedule.start()
            # Speak morning briefing shortly after startup (DISABLED TO PREVENT SPAM)
            # self._schedule.trigger_morning_now()
            print("[Schedule] Started.")
        except Exception as e:
            print(f"[Schedule] Init error: {e}")

    def _voice_state_update(self, state: str):
        """Called from VoiceEngine thread — update status label on main thread."""
        from astraeus_voice import STATE_UI
        text, colour = STATE_UI.get(state, ("", "#888888"))
        self.root.after(0, lambda t=text, c=colour: self.voice_status_label.config(text=t, fg=c))
        # While listening: change mic button colour
        if state == "listening":
            self.root.after(0, lambda: self.mic_button.config(bg="#8b1a1a"))
        else:
            self.root.after(0, lambda: self.mic_button.config(bg=self.button_bg))

    def _voice_push_to_talk(self):
        """Mic button pressed: start listening, send transcript as message when done."""
        if not self._voice_engine or not self._voice_engine.is_ready:
            self._show_voice_setup_dialog()
            return
        if self._voice_engine.is_listening:
            self._voice_engine.stop_listening()
            return

        def _on_result(text: str):
            if not text:
                self.root.after(0, lambda: self.voice_status_label.config(
                    text="(nothing heard)", fg="#888888"))
                return
            # Put transcript in the input box and send
            def _send():
                self.chat_input.delete(1.0, tk.END)
                self.chat_input.insert(tk.END, text)
                self.send_message()
            self.root.after(0, _send)

        def _on_partial(partial: str):
            # Show partial in the input box live
            self.root.after(0, lambda p=partial: (
                self.chat_input.delete(1.0, tk.END),
                self.chat_input.insert(tk.END, p),
            ))

        self._voice_engine.listen_async(on_result=_on_result, on_partial=_on_partial)

    def _voice_toggle_tts(self):
        """Toggle auto-speak AI responses."""
        self._voice_tts_on = not self._voice_tts_on
        if self._voice_tts_on:
            self.tts_button.config(text="🔊", fg=self.accent_color)
            # Stop any current speech when turning off
        else:
            self.tts_button.config(text="🔇", fg="#888888")
            if self._voice_engine:
                self._voice_engine.stop_speaking()

    def _voice_toggle_language(self):
        """Switch STT listening language between DE and EN."""
        if not self._voice_engine:
            return
        current = self._voice_engine._config.get("stt_active", "de")
        new_lang = "en" if current == "de" else "de"
        self._voice_engine.set_stt_language(new_lang)
        label = "EN" if new_lang == "en" else "DE"
        self.stt_lang_button.config(text=label)

    def _show_voice_setup_dialog(self):
        """Show a dialog with setup instructions when voice isn't ready."""
        from tkinter import messagebox
        if self._voice_engine:
            issues = self._voice_engine.check_dependencies()
            msg = "Voice setup needed:\n\n" + "\n\n".join(issues)
        else:
            msg = (
                "Voice engine konnte nicht geladen werden.\n\n"
                "Install: pip3 install faster-whisper sounddevice numpy piper-tts --break-system-packages\n\n"
                "TTS voices (.onnx + .onnx.json) ins IDE-Verzeichnis legen:\n"
                "  de_DE-thorsten_emotional-medium.onnx\n"
                "  en_US-joe-medium.onnx\n"
                "  → huggingface.co/rhasspy/piper-voices\n\n"
                "STT: faster-whisper lädt das Modell automatisch beim ersten Start."
            )
        messagebox.showinfo("Voice Setup", msg)

    def on_exit(self):
        # Stop schedule and voice cleanly
        try:
            if self._schedule:
                self._schedule.stop()
        except Exception:
            pass
        try:
            if self._voice_engine:
                self._voice_engine.stop_speaking()
        except Exception:
            pass
        # Graceful shutdown: stop model server, terminal connector, close DBs, then destroy
        try:
            # Crucial: Stop the model server and kill ALL llama-server processes to prevent background lingering
            if hasattr(self, 'stop_model_server'):
                self.stop_model_server()
        except Exception:
            pass

        try:
            for tab in getattr(self, '_terminal_tabs', []):
                try:
                    if tab.get('connector'):
                        tab['connector'].stop()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if getattr(self, 'memory_manager', None) and hasattr(self.memory_manager, 'conn'):
                try:
                    self.memory_manager.close()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if getattr(self, 'db_manager', None):
                try:
                    if getattr(self.db_manager, '_mode', None) == 'sqlite' and hasattr(self.db_manager, '_sqlite'):
                        if getattr(self.db_manager._sqlite, 'conn', None):
                            self.db_manager._sqlite.conn.close()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            try:
                self.root.quit()
            except Exception:
                pass

    def new_file(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if file_path:
            with open(file_path, 'w') as file:
                file.write(self.editor_text.get(1.0, tk.END))
            self._current_file_path = file_path
            self.root.after(100, self.refresh_file_tree)

    def clear_workspace(self):
        """Open a fresh empty tab."""
        self._new_editor_tab()

    # ------------------------------------------------------------------ #
    #  Backup helpers                                                      #
    # ------------------------------------------------------------------ #

    def _make_timestamped_backup(self, path: str):
        """Copy path → path.bak_YYYYMMDD_HHMMSS. Keep the 5 newest, delete older ones."""
        if not os.path.isfile(path):
            return
        import glob
        ts  = time.strftime('%Y%m%d_%H%M%S')
        bak = f"{path}.bak_{ts}"
        try:
            shutil.copy2(path, bak)
        except Exception as e:
            print(f"[backup] {e}")
            return
        # Prune old backups — keep 5 newest
        all_baks = sorted(glob.glob(f"{path}.bak_*"))
        for old in all_baks[:-5]:
            try:
                os.remove(old)
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    #  Diff viewer                                                         #
    # ------------------------------------------------------------------ #

    def _show_diff(self):
        """Show a colored unified diff between the current file and its latest backup."""
        import difflib, glob
        path = getattr(self, '_current_file_path', None)
        if not path or not os.path.isfile(path):
            messagebox.showinfo("Diff", "Keine Datei geöffnet.")
            return
        # Collect all known backup variants, newest last
        baks = sorted(glob.glob(f"{path}.bak_*"))          # timestamped: file.py.bak_20250520_…
        for suffix in ('.bak', '.backup', '.orig', '.old'):
            candidate = path + suffix
            if os.path.isfile(candidate) and candidate not in baks:
                baks.append(candidate)
        if not baks:
            messagebox.showinfo("Diff", "Kein Backup für diese Datei gefunden.\n"
                                        "Speichere die Datei einmal — danach wird automatisch ein Backup angelegt.")
            return
        latest = baks[-1]
        try:
            old_lines = open(latest,  encoding='utf-8', errors='replace').readlines()
            new_lines = open(path,    encoding='utf-8', errors='replace').readlines()
        except Exception as e:
            messagebox.showerror("Diff", str(e))
            return
        diff = list(difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"alt  ({os.path.basename(latest)})",
            tofile  =f"neu  ({os.path.basename(path)})",
            lineterm='',
        ))
        win = tk.Toplevel(self.root)
        win.title(f"Diff — {os.path.basename(path)}")
        win.geometry("1000x650")
        win.configure(bg=self.bg_color)
        txt = scrolledtext.ScrolledText(win, wrap=tk.NONE,
                                        bg='#120a1a', fg='#c0a8c0',
                                        font=('Courier New', 10),
                                        insertbackground='white')
        txt.pack(expand=True, fill='both', padx=6, pady=6)
        txt.tag_configure('add', foreground='#5de05d', background='#0a200a')
        txt.tag_configure('rem', foreground='#e05555', background='#200a0a')
        txt.tag_configure('hdr', foreground='#7ab0f0', background='#0a0a25')
        txt.tag_configure('ctx', foreground='#808080')
        if not diff:
            txt.insert(tk.END, "(Keine Unterschiede — Datei ist identisch mit dem Backup.)", 'ctx')
        else:
            for line in diff:
                if line.startswith('+++') or line.startswith('---') or line.startswith('@@'):
                    txt.insert(tk.END, line + '\n', 'hdr')
                elif line.startswith('+'):
                    txt.insert(tk.END, line + '\n', 'add')
                elif line.startswith('-'):
                    txt.insert(tk.END, line + '\n', 'rem')
                else:
                    txt.insert(tk.END, line + '\n', 'ctx')
        txt.configure(state='disabled')

    # ------------------------------------------------------------------ #
    #  Apply last code block from chat to editor                          #
    # ------------------------------------------------------------------ #

    def _apply_chat_code_to_file(self):
        """Find the last ```...``` block in the chat and put it in the editor."""
        try:
            chat_text = self.chat_display.get('1.0', tk.END)
        except Exception:
            return
        # Match ```optional_lang\n...``` — non-greedy, any content
        blocks = _re.findall(r'```(?:[^\n]*)\n(.*?)```', chat_text, _re.DOTALL)
        if not blocks:
            messagebox.showinfo("Apply Code", "Kein Code-Block im Chat gefunden.\n"
                                              "Das Modell muss einen ```...``` Block gepostet haben.")
            return
        code = blocks[-1]  # always take the last block
        # Put into editor (make backup first if file is open)
        path = getattr(self, '_current_file_path', None)
        if path and os.path.isfile(path):
            self._make_timestamped_backup(path)
        self.editor_text.delete('1.0', tk.END)
        self.editor_text.insert('1.0', code)
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(code)
                self.editor_label.config(text=f"Workspace — applied & saved: {os.path.basename(path)}")
                self.editor_text.after(3000, lambda: self.editor_label.config(text="Workspace"))
                self.root.after(100, self.refresh_file_tree)
                messagebox.showinfo("Apply Code", f"Letzter Code-Block angewendet und gespeichert:\n{path}")
            except Exception as e:
                messagebox.showerror("Apply Code", f"Konnte nicht speichern: {e}")
        else:
            messagebox.showinfo("Apply Code",
                                "Code in Editor übertragen.\n"
                                "Kein Speicherpfad — bitte 'Save As...' verwenden.")

    # ------------------------------------------------------------------ #
    #  Backup cleanup dialog                                               #
    # ------------------------------------------------------------------ #

    def _clean_backups(self):
        """List all .bak_* files under the open project folder and offer to delete them."""
        import glob
        root_path = self.path_var.get()
        if not os.path.isdir(root_path):
            messagebox.showwarning("Backups", "Kein Projekt-Ordner geöffnet.")
            return
        all_baks = sorted(set(
            glob.glob(os.path.join(root_path, '**', '*.bak_*'),  recursive=True) +
            glob.glob(os.path.join(root_path, '**', '*.bak'),    recursive=True) +
            glob.glob(os.path.join(root_path, '**', '*.backup'), recursive=True) +
            glob.glob(os.path.join(root_path, '**', '*.orig'),   recursive=True) +
            glob.glob(os.path.join(root_path, '**', '*.old'),    recursive=True)
        ))
        if not all_baks:
            messagebox.showinfo("Backups", "Keine Backup-Dateien im Projekt gefunden.")
            return
        win = tk.Toplevel(self.root)
        win.title("Backup-Dateien löschen")
        win.geometry("700x450")
        win.configure(bg=self.bg_color)
        win.grab_set()
        Label(win, text=f"{len(all_baks)} Backup-Dateien gefunden:",
              bg=self.bg_color, fg=self.fg_color,
              font=('Arial', 10, 'bold')).pack(anchor='w', padx=10, pady=(8, 2))
        lb_frame = Frame(win, bg=self.bg_color)
        lb_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        sb = tk.Scrollbar(lb_frame)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        lb = tk.Listbox(lb_frame, yscrollcommand=sb.set, selectmode=tk.EXTENDED,
                        bg=self.entry_bg, fg=self.fg_color, selectbackground=self.button_bg,
                        font=('Courier New', 9))
        lb.pack(fill=tk.BOTH, expand=True)
        sb.config(command=lb.yview)
        for bak in all_baks:
            lb.insert(tk.END, os.path.relpath(bak, root_path))
        lb.select_set(0, tk.END)   # select all by default
        btn_row = Frame(win, bg=self.bg_color)
        btn_row.pack(fill=tk.X, padx=10, pady=8)
        def _delete_selected():
            sel = lb.curselection()
            if not sel:
                return
            paths = [all_baks[i] for i in sel]
            if not messagebox.askyesno("Löschen",
                                       f"{len(paths)} Backup-Datei(en) wirklich löschen?"):
                return
            errors = []
            for p in paths:
                try:
                    os.remove(p)
                except Exception as e:
                    errors.append(f"{os.path.basename(p)}: {e}")
            win.destroy()
            if errors:
                messagebox.showerror("Fehler", "\n".join(errors))
            else:
                messagebox.showinfo("Fertig", f"{len(paths)} Backup-Datei(en) gelöscht.")
        Button(btn_row, text="Ausgewählte löschen", command=_delete_selected,
               bg=self.button_bg, fg=self.button_fg).pack(side=tk.LEFT, padx=4)
        Button(btn_row, text="Alle markieren",
               command=lambda: lb.select_set(0, tk.END),
               bg=self.button_bg, fg=self.button_fg).pack(side=tk.LEFT, padx=4)
        Button(btn_row, text="Schließen", command=win.destroy,
               bg=self.button_bg, fg=self.button_fg).pack(side=tk.RIGHT, padx=4)

    def save_file(self):
        # Use the tracked current file path; fall back to explorer selection
        file_path = getattr(self, '_current_file_path', None)
        if not file_path:
            selection = self.file_tree.selection()
            if not selection or not os.path.isfile(selection[0]):
                messagebox.showwarning("Save File", "No file is currently open")
                return
            file_path = selection[0]
        try:
            self._make_timestamped_backup(file_path)   # backup before overwriting
            # 'end-1c' strips the extra newline Tkinter always appends
            content = self.editor_text.get(1.0, 'end-1c')
            with open(file_path, 'w', encoding='utf-8') as file:
                file.write(content)
            self._set_open_file(file_path)
            self.editor_label.config(text=f"Workspace — saved: {os.path.basename(file_path)}")
            self.editor_text.after(3000, lambda: self.editor_label.config(text="Workspace"))
            self.root.after(100, self.refresh_file_tree)
        except Exception as e:
            messagebox.showerror("Save File", f"Failed to save file: {e}")

    def save_file_as(self):
        file_path = filedialog.asksaveasfilename(
            defaultextension="",
            filetypes=[
                ("Python files", "*.py"),
                ("Text files", "*.txt"),
                ("C++ files", "*.cpp *.h"),
                ("All files", "*.*"),
            ],
            initialfile=os.path.basename(self._current_file_path) if self._current_file_path else "",
        )
        if not file_path:
            return
        try:
            content = self.editor_text.get(1.0, 'end-1c')
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            self._set_open_file(file_path)
            self.editor_label.config(text=f"Workspace — saved: {os.path.basename(file_path)}")
            self.editor_text.after(3000, lambda: self.editor_label.config(text="Workspace"))
            self.root.after(100, self.refresh_file_tree)
        except Exception as e:
            messagebox.showerror("Save As", f"Failed to save file: {e}")

    def adjust_terminal_height(self):
        # We disabled the dynamic height logic for now because it was keeping the terminal too high
        # Now the terminal's height is fixed by the center_container.grid_rowconfigure minsize.
        pass

if __name__ == "__main__":
    root = tk.Tk()
    app = MainWindow(root)
    root.mainloop()
