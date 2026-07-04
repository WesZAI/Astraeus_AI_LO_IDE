# ==========================================
# Copyright (c) 2026 Gabriela Berger AI Oberland
# All Rights Reserved.
# This code is subject to the custom NON-COMMERCIAL 
# & ANTI-CORPORATE LICENSE (Maximum 20 PCs) found in the LICENSE file.
# ==========================================
"""agent_tools.py

Workspace-scoped tools the AI can call. Every path goes through `_safe`
so the agent cannot read or write outside the chosen workspace folder.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


_DEFAULT_IGNORE = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", "dist", "build",
}


class WorkspaceTools:
    def __init__(self, workspace_root: str):
        self.root = Path(workspace_root).expanduser().resolve()

    def set_root(self, workspace_root: str) -> None:
        self.root = Path(workspace_root).expanduser().resolve()

    def _safe(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = self.root / p
        try:
            p_resolved = p.resolve()
        except OSError:
            p_resolved = p
        try:
            p_resolved.relative_to(self.root)
        except ValueError as e:
            raise PermissionError(
                f"path {p_resolved} is outside workspace {self.root}"
            ) from e
        return p_resolved

    def _rel(self, p: Path) -> str:
        try:
            r = str(p.relative_to(self.root))
            return r if r != "." else "."
        except ValueError:
            return str(p)

    # ---- read --------------------------------------------------------
    def list_dir(self, path: str = ".") -> Dict[str, Any]:
        p = self._safe(path)
        if not p.is_dir():
            return {"error": f"not a directory: {self._rel(p)}"}
        items = []
        for entry in sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            items.append({
                "name": entry.name,
                "type": "dir" if entry.is_dir() else "file",
                "size": entry.stat().st_size if entry.is_file() else None,
            })
        return {"path": self._rel(p), "items": items}

    def workspace_tree(self, max_depth: int = 4, ignore: Optional[List[str]] = None) -> Dict[str, Any]:
        ignore_set = set(ignore or []) | _DEFAULT_IGNORE
        out: List[Dict[str, Any]] = []
        for cur, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if d not in ignore_set]
            rel = Path(cur).relative_to(self.root)
            depth = 0 if str(rel) == "." else len(rel.parts)
            if depth > max_depth:
                dirs[:] = []
                continue
            out.append({
                "dir": str(rel) if str(rel) != "." else ".",
                "subdirs": sorted(dirs),
                "files": sorted(files),
            })
        return {"root": str(self.root), "tree": out}

    def read_file(self, path: str, max_bytes: int = 400_000) -> Dict[str, Any]:
        p = self._safe(path)
        if not p.is_file():
            return {"error": f"not a file: {self._rel(p)}"}
        size = p.stat().st_size
        if size > max_bytes:
            return {"error": f"file too large: {size} bytes (limit {max_bytes})"}
        try:
            return {
                "path": self._rel(p),
                "content": p.read_text(encoding="utf-8", errors="replace"),
                "bytes": size,
            }
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

    def search(self, pattern: str, path: str = ".", regex: bool = False, max_results: int = 200) -> Dict[str, Any]:
        base = self._safe(path)
        if regex:
            try:
                rx = re.compile(pattern)
            except re.error as e:
                return {"error": f"bad regex: {e}"}
            match = lambda line: rx.search(line) is not None
        else:
            needle = pattern
            match = lambda line: needle in line
        hits = []
        for cur, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in _DEFAULT_IGNORE]
            for fn in files:
                fp = Path(cur) / fn
                try:
                    with fp.open("r", encoding="utf-8", errors="replace") as f:
                        for i, line in enumerate(f, 1):
                            if match(line):
                                hits.append({
                                    "path": self._rel(fp),
                                    "line": i,
                                    "text": line.rstrip("\n")[:300],
                                })
                                if len(hits) >= max_results:
                                    return {"pattern": pattern, "hits": hits, "truncated": True}
                except Exception:
                    continue
        return {"pattern": pattern, "hits": hits, "truncated": False}

    # ---- write -------------------------------------------------------
    def write_file(self, path: str, content: str, backup: bool = True) -> Dict[str, Any]:
        p = self._safe(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        had_backup = False
        if backup and p.exists() and p.is_file():
            shutil.copy2(p, p.with_suffix(p.suffix + ".bak"))
            had_backup = True
        p.write_text(content, encoding="utf-8")
        return {"ok": True, "path": self._rel(p), "bytes": len(content), "backup": had_backup}

    def append_file(self, path: str, content: str) -> Dict[str, Any]:
        p = self._safe(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(content)
        return {"ok": True, "path": self._rel(p)}

    def copy_file(self, src: str, dst: str) -> Dict[str, Any]:
        s = self._safe(src)
        d = self._safe(dst)
        if not s.exists():
            return {"error": f"source missing: {self._rel(s)}"}
        d.parent.mkdir(parents=True, exist_ok=True)
        if s.is_dir():
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)
        return {"ok": True, "src": self._rel(s), "dst": self._rel(d)}

    def move_file(self, src: str, dst: str) -> Dict[str, Any]:
        s = self._safe(src)
        d = self._safe(dst)
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s), str(d))
        return {"ok": True, "src": self._rel(s), "dst": self._rel(d)}

    def delete_file(self, path: str) -> Dict[str, Any]:
        p = self._safe(path)
        if p == self.root:
            return {"error": "refusing to delete workspace root"}
        if p.is_file():
            p.unlink()
            return {"ok": True, "deleted": self._rel(p)}
        if p.is_dir():
            shutil.rmtree(p)
            return {"ok": True, "deleted_dir": self._rel(p)}
        return {"error": f"not found: {self._rel(p)}"}

    def make_dir(self, path: str) -> Dict[str, Any]:
        p = self._safe(path)
        p.mkdir(parents=True, exist_ok=True)
        return {"ok": True, "path": self._rel(p)}

    # ---- run ---------------------------------------------------------
    def run_bash(self, command: str, timeout: int = 900) -> Dict[str, Any]:
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {
                "stdout": result.stdout[-20000:],
                "stderr": result.stderr[-20000:],
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"error": f"timeout after {timeout}s"}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}


# ---- tool description / parsing ------------------------------------------

def tool_schemas() -> List[Dict[str, Any]]:
    return [
        {"name": "list_dir", "args": "path: string ('.')", "desc": "list files/dirs in a workspace folder"},
        {"name": "workspace_tree", "args": "max_depth: int (4)", "desc": "recursive tree of the whole workspace"},
        {"name": "read_file", "args": "path: string", "desc": "read a file's contents"},
        {"name": "search", "args": "pattern: string, path: string ('.'), regex: bool (false)", "desc": "search file contents"},
        {"name": "write_file", "args": "path: string, content: string, backup: bool (true)", "desc": "create/overwrite file (auto .bak)"},
        {"name": "append_file", "args": "path: string, content: string", "desc": "append text to a file"},
        {"name": "copy_file", "args": "src: string, dst: string", "desc": "copy file or directory"},
        {"name": "move_file", "args": "src: string, dst: string", "desc": "move/rename file or directory"},
        {"name": "delete_file", "args": "path: string", "desc": "delete file or directory"},
        {"name": "make_dir", "args": "path: string", "desc": "create directory (mkdir -p)"},
        {"name": "run_bash", "args": "command: string, timeout: int (900)", "desc": "run a shell command in the workspace cwd"},
    ]


def tool_prompt() -> str:
    lines = [
        "You can act on the workspace by emitting tool calls in this exact format:",
        "<tool_call>",
        '{"name": "<tool_name>", "arguments": { ... }}',
        "</tool_call>",
        "",
        "You may emit several <tool_call> blocks in one reply; all of them run and",
        "their JSON results come back to you in the next turn. When you have enough",
        "info, answer the user normally with NO <tool_call> block — that ends the loop.",
        "",
        "Rules:",
        "- All paths are relative to the workspace root (or absolute inside it).",
        "- Anything outside the workspace will be refused.",
        "- Do not invent file contents — read with read_file first.",
        "- Prefer doing the work (use tools) over describing what you would do.",
        "",
        "Available tools:",
    ]
    for s in tool_schemas():
        lines.append(f"- {s['name']}({s['args']}) — {s['desc']}")
    return "\n".join(lines)


_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


def parse_tool_calls(text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for m in _TOOL_CALL_RE.finditer(text or ""):
        raw = m.group(1)
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out


def strip_tool_calls(text: str) -> str:
    return _TOOL_CALL_RE.sub("", text or "").strip()


def dispatch(tools: WorkspaceTools, call: Dict[str, Any]) -> Dict[str, Any]:
    name = call.get("name")
    args = call.get("arguments") or {}
    if not isinstance(name, str) or name.startswith("_"):
        return {"error": f"invalid tool name: {name!r}"}
    fn = getattr(tools, name, None)
    if not callable(fn):
        return {"error": f"unknown tool: {name}"}
    if not isinstance(args, dict):
        return {"error": "arguments must be an object"}
    try:
        return fn(**args)
    except TypeError as e:
        return {"error": f"bad arguments: {e}"}
    except PermissionError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


__all__ = [
    "WorkspaceTools",
    "tool_schemas",
    "tool_prompt",
    "parse_tool_calls",
    "strip_tool_calls",
    "dispatch",
]
