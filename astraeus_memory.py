# ==========================================
# Copyright (c) 2026 Gabriela Berger AI Oberland
# All Rights Reserved.
# This code is subject to the custom NON-COMMERCIAL 
# & ANTI-CORPORATE LICENSE (Maximum 20 PCs) found in the LICENSE file.
# ==========================================
"""astraeus_memory.py — Per-folder memory engine for Astraeus IDE.

Creates and maintains two files in every folder that Astraeus touches:

  astraeus.md   — Human-readable summary, key files, notes, activity log.
                  Like CLAUDE.md but written and updated by Astraeus itself.

  astraeus.json — Machine-readable keyword-frequency vector + metadata.
                  Used for fast similarity search across the whole filesystem
                  without re-scanning (the "AI retrieval" layer).

A background thread refreshes all known folders every 20 minutes.
New folders trigger an immediate scan in a worker thread.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional


# ── Constants ────────────────────────────────────────────────────────────────

_IGNORE_NAMES = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "env",
    ".mypy_cache", ".pytest_cache", "dist", "build", "target",
    "astraeus.md", "astraeus.json", ".DS_Store", "Thumbs.db",
}
_TEXT_EXTS = {
    ".py", ".md", ".txt", ".js", ".ts", ".html", ".css", ".json",
    ".yaml", ".yml", ".toml", ".cfg", ".ini", ".sh", ".bash",
    ".cpp", ".c", ".h", ".hpp", ".rs", ".go", ".java", ".rb",
    ".php", ".sql", ".xml", ".csv", ".rst", ".tex", ".r", ".lua",
    ".pl", ".swift", ".kt", ".vue", ".jsx", ".tsx", ".env",
    ".conf", ".dockerfile", ".makefile", ".gitignore", ".editorconfig",
}
_STOP_WORDS = {
    # English
    "the", "and", "for", "are", "but", "not", "you", "all", "can",
    "her", "was", "one", "our", "out", "had", "has", "have", "that",
    "this", "with", "from", "they", "will", "been", "when", "who",
    "did", "its", "let", "put", "say", "she", "too", "use",
    # Python keywords / noise
    "self", "return", "import", "from", "class", "def", "none",
    "true", "false", "pass", "elif", "else", "elif",
    "print", "str", "int", "float", "list", "dict", "set",
    # German common words
    "die", "der", "das", "und", "oder", "ist", "ein", "eine", "sich",
    "mit", "bei", "von", "zum", "zur", "den", "dem", "des", "auch",
    "nicht", "noch", "aber", "wenn", "dann", "wie", "was", "ich",
    "sie", "wir", "ihr", "ihn", "ihm", "uns",
}
_EXT_TO_TAG = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".html": "web", ".css": "web", ".cpp": "cpp", ".c": "c",
    ".rs": "rust", ".go": "golang", ".java": "java", ".rb": "ruby",
    ".sh": "shell", ".bash": "shell", ".md": "documentation",
    ".tex": "latex", ".sql": "database", ".r": "r-lang",
    ".lua": "lua", ".swift": "swift", ".kt": "kotlin",
}
_KW_TO_TAG = {
    "resume": "cv", "lebenslauf": "cv", "curriculum": "cv",
    "bewerbung": "bewerbung", "anschreiben": "cover-letter",
    "email": "email", "mail": "email", "smtp": "email",
    "game": "game", "pygame": "game", "godot": "game",
    "neural": "ai", "model": "ai", "training": "ai",
    "torch": "ai", "tensorflow": "ai", "dataset": "ai",
    "server": "server", "api": "api", "endpoint": "api",
    "flask": "python-web", "django": "python-web", "fastapi": "python-web",
    "database": "database", "sqlite": "database", "postgres": "database",
    "docker": "docker", "kubernetes": "devops", "terraform": "devops",
    "test": "testing", "pytest": "testing", "unittest": "testing",
    "config": "config", "setup": "setup",
}
_FOLDER_NAME_TAGS = {
    "doc": "documents", "docs": "documents", "note": "documents",
    "bewerbung": "bewerbung", "cv": "cv", "lebenslauf": "cv",
    "code": "code", "src": "code", "source": "code", "dev": "code",
    "game": "game", "spiel": "game",
    "bild": "images", "photo": "images", "image": "images", "pic": "images",
    "music": "music", "musik": "music", "audio": "music",
    "video": "video", "film": "video", "movie": "video",
    "download": "downloads", "tmp": "temp", "temp": "temp",
    "backup": "backup", "archiv": "archive", "archive": "archive",
}
MAX_FILES_PER_SCAN = 300
MAX_TEXT_BYTES = 150_000
MAX_ACTIVITY_LOG = 100
MAX_KEY_FILES_MD = 25
TOP_KEYWORDS = 80


# ── Public class ─────────────────────────────────────────────────────────────

class FolderMemory:
    """
    Manages per-folder astraeus.md + astraeus.json files.
    Call start() once; it runs a background refresh thread.
    """

    def __init__(self, interval_minutes: int = 20):
        self._interval = interval_minutes * 60
        self._folders: set[str] = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._current: str = str(Path.home())
        self._thread: Optional[threading.Thread] = None

    # ── lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._bg_loop, daemon=True, name="astraeus-memory"
        )
        self._thread.start()
        print(f"[FolderMemory] background updater started (interval: {self._interval // 60} min)")

    def stop(self) -> None:
        self._stop.set()

    # ── public API ────────────────────────────────────────────────────────

    def set_folder(self, path: str) -> None:
        """Register a folder as active. Triggers an immediate async scan if new."""
        resolved = str(Path(path).resolve())
        self._current = resolved
        is_new = False
        with self._lock:
            if resolved not in self._folders:
                self._folders.add(resolved)
                is_new = True
        if is_new:
            threading.Thread(
                target=self._safe_update,
                args=(resolved,),
                daemon=True,
                name=f"mem-init-{Path(resolved).name}",
            ).start()

    def log_activity(self, path: str, action: str) -> None:
        """Append one activity line to the folder's JSON without a full rescan."""
        p = Path(path).resolve()
        json_path = p / "astraeus.json"
        if not json_path.exists():
            return
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            log: list = data.get("recent_activity", [])
            log.insert(0, {
                "timestamp": datetime.now().isoformat(),
                "action": action[:250],
            })
            data["recent_activity"] = log[:MAX_ACTIVITY_LOG]
            json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        except Exception:
            pass

    def get_context_block(self, path: str) -> str:
        """Return the astraeus.md for a folder (up to 100 lines) for the system prompt."""
        md = Path(path).resolve() / "astraeus.md"
        if not md.exists():
            return ""
        try:
            lines = md.read_text(encoding="utf-8", errors="replace").splitlines()
            return "\n".join(lines[:100])
        except Exception:
            return ""

    def update_now(self, path: str, ai_notes: str = "", activity: str = "") -> str:
        """Force an immediate synchronous update of a folder's memory files."""
        p = Path(path).resolve()
        if not p.is_dir():
            return f"Not a directory: {path}"
        with self._lock:
            self._folders.add(str(p))
        return _write_memory(p, ai_notes=ai_notes, activity=activity)

    def search(self, query: str, start_path: str = "/") -> list[dict]:
        """
        Search all astraeus.json files under start_path.
        Returns folders ranked by keyword-vector similarity to the query.
        """
        try:
            r = subprocess.run(
                f'find "{start_path}" -name "astraeus.json" 2>/dev/null',
                shell=True, capture_output=True, text=True, timeout=45,
            )
            files = [l.strip() for l in r.stdout.splitlines() if l.strip()]
        except Exception:
            return []

        query_tokens = set(_tokenize(query))
        results = []
        for fpath in files:
            try:
                data = json.loads(Path(fpath).read_text(encoding="utf-8"))
                kw = data.get("keywords", {})
                tags = set(data.get("tags", []))
                score = sum(kw.get(w, 0.0) for w in query_tokens)
                score += 0.4 * sum(1 for t in tags if t in query_tokens)
                # Boost if query word appears in folder name
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
        return results[:20]

    # ── internals ─────────────────────────────────────────────────────────

    def _bg_loop(self) -> None:
        while not self._stop.wait(self._interval):
            with self._lock:
                folders = set(self._folders)
            for folder in folders:
                self._safe_update(folder)

    def _safe_update(self, path: str) -> None:
        try:
            _write_memory(Path(path))
        except Exception as e:
            print(f"[FolderMemory] update failed for {path}: {e}")


# ── Module-level helpers (used by both FolderMemory and mcp_server) ──────────

def _tokenize(text: str) -> list[str]:
    words = re.findall(r'\b[a-zA-ZäöüÄÖÜß]{3,}\b', text.lower())
    return [w for w in words if w not in _STOP_WORDS]


def _infer_tags(file_types: Counter, keywords: dict, path: Path) -> list[str]:
    tags: set[str] = set()
    for ext, tag in _EXT_TO_TAG.items():
        if file_types.get(ext, 0) > 0:
            tags.add(tag)
    for kw, tag in _KW_TO_TAG.items():
        if kw in keywords:
            tags.add(tag)
    name_lower = path.name.lower()
    for part, tag in _FOLDER_NAME_TAGS.items():
        if part in name_lower:
            tags.add(tag)
    return sorted(tags)


def scan_folder(p: Path) -> dict:
    """Scan a folder and return the raw data dict (no file I/O)."""
    files_info: list[dict] = []
    file_types: Counter = Counter()
    total_size = 0
    all_tokens: list[str] = []

    try:
        entries = sorted(p.iterdir(), key=lambda e: (e.is_dir(), e.name.lower()))
    except PermissionError:
        entries = []

    for entry in entries:
        if entry.name in _IGNORE_NAMES or entry.name.startswith("."):
            continue
        if len(files_info) >= MAX_FILES_PER_SCAN:
            break
        if not entry.is_file():
            continue
        try:
            size = entry.stat().st_size
            total_size += size
        except Exception:
            size = 0

        ext = entry.suffix.lower()
        file_types[ext or "(no ext)"] += 1

        hint = ""
        if ext in _TEXT_EXTS and size < MAX_TEXT_BYTES:
            try:
                text = entry.read_text(encoding="utf-8", errors="replace")
                all_tokens.extend(_tokenize(text[:10_000]))
                for line in text.splitlines()[:30]:
                    stripped = line.strip()
                    if stripped and not stripped.startswith(("#!/", "#!")):
                        if stripped.startswith(("#", "//", '"""', "'''", "/*")):
                            hint = stripped.lstrip("#/\"' *").strip()[:120]
                            break
            except Exception:
                pass

        files_info.append({"name": entry.name, "size": size, "hint": hint})

    freq = Counter(all_tokens)
    total_t = sum(freq.values()) or 1
    keywords = {w: round(c / total_t, 6) for w, c in freq.most_common(TOP_KEYWORDS)}

    tags = _infer_tags(file_types, keywords, p)

    summary = (
        f"{p.name} | "
        + ", ".join(f"{e}×{n}" for e, n in file_types.most_common(4))
        + (f" | [{', '.join(tags[:5])}]" if tags else "")
    )

    return {
        "folder": str(p),
        "last_updated": datetime.now().isoformat(),
        "version": 2,
        "summary": summary,
        "file_count": len(files_info),
        "file_types": dict(file_types.most_common(20)),
        "total_size_bytes": total_size,
        "key_files": files_info[:30],
        "tags": tags,
        "keywords": keywords,
        "recent_activity": [],
        "ai_notes": "",
    }


def _write_memory(
    p: Path,
    ai_notes: str = "",
    activity: str = "",
) -> str:
    """Core write: scan folder, merge existing data, write both files."""
    json_path = p / "astraeus.json"
    md_path = p / "astraeus.md"

    # Load existing preserved fields
    existing: dict = {}
    if json_path.exists():
        try:
            existing = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    data = scan_folder(p)

    # Preserve human-customised summary (doesn't start with the auto-prefix)
    if existing.get("summary") and not existing["summary"].startswith(f"{p.name} |"):
        data["summary"] = existing["summary"]

    # Merge AI notes
    data["ai_notes"] = ai_notes or existing.get("ai_notes", "")

    # Merge activity log
    log: list = existing.get("recent_activity", [])
    if activity:
        log.insert(0, {
            "timestamp": datetime.now().isoformat(),
            "action": activity[:250],
        })
    data["recent_activity"] = log[:MAX_ACTIVITY_LOG]

    # Write
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(_render_md(p, data), encoding="utf-8")

    return f"Memory updated: {p}"


def _render_md(p: Path, data: dict) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# Astraeus Memory — `{p.name}`",
        f"> Path: `{p}`  |  Updated: {now}",
        "",
        "## Summary",
        data.get("summary", ""),
        "",
    ]

    tags = data.get("tags", [])
    if tags:
        lines += ["## Tags", "  ".join(f"`{t}`" for t in tags), ""]

    lines += [
        "## Files",
        f"- **Count:** {data.get('file_count', 0)}",
        f"- **Size:** {data.get('total_size_bytes', 0):,} bytes",
    ]
    ft = data.get("file_types", {})
    if ft:
        lines.append(
            "- **Types:** " + "  ".join(f"`{e}`×{n}" for e, n in list(ft.items())[:10])
        )

    key_files = data.get("key_files", [])
    if key_files:
        lines += ["", "## Key Files"]
        for f in key_files[:MAX_KEY_FILES_MD]:
            hint = f"  — _{f['hint']}_" if f.get("hint") else ""
            size_kb = f.get("size", 0) / 1024
            lines.append(f"- `{f['name']}` ({size_kb:.1f} KB){hint}")

    kws = list(data.get("keywords", {}).keys())[:20]
    if kws:
        lines += ["", "## Keywords", "  ".join(f"`{k}`" for k in kws)]

    notes = data.get("ai_notes", "")
    if notes:
        lines += ["", "## Astraeus Notes", notes]

    activity = data.get("recent_activity", [])
    if activity:
        lines += ["", "## Recent Activity"]
        for item in activity[:15]:
            ts = item.get("timestamp", "")[:16].replace("T", " ")
            act = item.get("action", "")
            lines.append(f"- `{ts}` {act}")

    return "\n".join(lines) + "\n"
