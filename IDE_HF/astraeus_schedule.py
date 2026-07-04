# ==========================================
# Copyright (c) 2026 Gabriela Berger AI Oberland
# All Rights Reserved.
# This code is subject to the custom NON-COMMERCIAL 
# & ANTI-CORPORATE LICENSE (Maximum 20 PCs) found in the LICENSE file.
# ==========================================
"""astraeus_schedule.py — Daily schedule for Astraeus.

Every day:
  08:00 CEST  → PC wakes (via RTC alarm set the night before)
               → Astraeus speaks morning briefing:
                  good morning + yesterday summary + today's plan + email count

  00:00 CEST  → Astraeus speaks farewell + today's summary
               → Sets RTC wake alarm for 08:00 next morning
               → Shuts down the PC

Timezone: Europe/Berlin  (CEST summer UTC+2, CET winter UTC+1)
Config  : ~/.config/astraeus/schedule_config.json
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

try:
    from zoneinfo import ZoneInfo
    _TZ_BERLIN = ZoneInfo("Europe/Berlin")
except ImportError:
    try:
        from dateutil.tz import gettz
        _TZ_BERLIN = gettz("Europe/Berlin")
    except ImportError:
        _TZ_BERLIN = None
        print("[Schedule] WARNING: zoneinfo/dateutil not found — timezone will be UTC")

_CFG_PATH = Path.home() / ".config" / "astraeus" / "schedule_config.json"

_DEFAULT_CFG = {
    "enabled": True,
    "shutdown_time": "00:00",   # midnight Berlin time
    "wakeup_time":  "08:00",    # 8 AM Berlin time
    "timezone": "Europe/Berlin",
    "warning_minutes": 3,       # speak farewell N minutes before shutdown
    "morning_delay_seconds": 8, # wait after IDE loads before speaking
    "language": "Deutsch",      # "Deutsch" or "English" — set once, stays forever
}

# ── Morning greeting templates (AI fills in the details) ─────────────────────

_MORNING_PROMPT = """You are the Astraeus PC. It is {time} on {weekday}, {date}.
The user just woke up and started their PC.

Write the morning briefing TWICE — first in German, then in English.
Use this exact format, nothing else:

[DE] <German greeting here>
[EN] <English greeting here>

Rules for each version:
- Maximum 3 short sentences.
- Sentence 1: Good morning greeting, mention the day.
- Sentence 2: What was worked on yesterday (pick 1-2 most relevant things from the activity).
- Sentence 3: One useful thing for today — a task, pending email, or encouraging word.
- Tone: calm, warm, like a trusted colleague — not a robot. Not too formal.

Yesterday's activity:
{activity}

Email inbox:
{emails}

Respond ONLY with the two lines [DE] and [EN]. No bullet points, no extra text."""

_FAREWELL_PROMPT = """You are the Astraeus PC. It is {time}, time to shut down.

Write the farewell TWICE — first in German, then in English.
Use this exact format, nothing else:

[DE] <German farewell here>
[EN] <English farewell here>

Rules for each version:
- Maximum 2 short sentences.
- Sentence 1: Brief summary of what was accomplished today (1-2 things from activity).
- Sentence 2: Calm goodnight / see you tomorrow.
- Tone: warm, calm. Not dramatic.

Today's activity:
{activity}

Respond ONLY with the two lines [DE] and [EN]. No extra text."""


class ScheduleManager:
    """
    Runs a background thread that fires the morning briefing and the nightly
    farewell+shutdown at the configured times.
    """

    def __init__(
        self,
        voice_engine,
        ai_call: Callable[[str], str],
        memory_search_path: str = "/home",
    ):
        self._voice = voice_engine
        self._ai = ai_call          # callable: prompt -> AI response string
        self._mem_root = memory_search_path
        self._cfg: dict = {}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._morning_done_today: Optional[str] = None   # date string, avoids double-firing
        self._farewell_done_today: Optional[str] = None
        self._load_config()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def _load_config(self) -> None:
        if _CFG_PATH.exists():
            try:
                self._cfg = json.loads(_CFG_PATH.read_text())
                return
            except Exception:
                pass
        self._cfg = dict(_DEFAULT_CFG)

    def save_config(self) -> None:
        _CFG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CFG_PATH.write_text(json.dumps(self._cfg, indent=2))

    def start(self) -> None:
        """Start the background schedule thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="astraeus-schedule"
        )
        self._thread.start()
        print(f"[Schedule] Started — shutdown {self._cfg['shutdown_time']}, "
              f"wakeup {self._cfg['wakeup_time']} ({self._cfg['timezone']})")

    def stop(self) -> None:
        self._stop.set()

    def trigger_morning_now(self) -> None:
        """Fire the morning briefing immediately (called on IDE startup)."""
        threading.Thread(
            target=self._do_morning, daemon=True, name="morning-briefing"
        ).start()

    # ── Background loop ───────────────────────────────────────────────────────

    def _run(self) -> None:
        """Check every 30 seconds whether it's time to act."""
        while not self._stop.wait(30):
            if not self._cfg.get("enabled", True):
                continue
            now = self._now_berlin()
            today_str = now.strftime("%Y-%m-%d")
            current_hm = now.strftime("%H:%M")

            shutdown_hm = self._cfg.get("shutdown_time", "00:00")
            warn_min = int(self._cfg.get("warning_minutes", 3))

            # Calculate warning time
            sh, sm = map(int, shutdown_hm.split(":"))
            warn_dt = now.replace(hour=sh, minute=sm, second=0, microsecond=0) \
                      - timedelta(minutes=warn_min)
            warn_hm = warn_dt.strftime("%H:%M")

            if current_hm == warn_hm and self._farewell_done_today != today_str:
                self._farewell_done_today = today_str
                threading.Thread(
                    target=self._do_farewell_and_shutdown,
                    daemon=True, name="farewell"
                ).start()

    def _now_berlin(self) -> datetime:
        if _TZ_BERLIN:
            return datetime.now(_TZ_BERLIN)
        return datetime.utcnow()

    # ── Morning briefing ──────────────────────────────────────────────────────

    def _do_morning(self) -> None:
        delay = int(self._cfg.get("morning_delay_seconds", 8))
        time.sleep(delay)   # let the IDE finish loading

        now = self._now_berlin()
        # Collect context
        activity = self._collect_recent_activity(hours=20)
        emails = self._check_email_count()
        now_berlin = self._now_berlin()
        weekday_de = _weekday_name(now_berlin, "Deutsch")

        prompt = _MORNING_PROMPT.format(
            time=now_berlin.strftime("%H:%M"),
            weekday=weekday_de,
            date=now_berlin.strftime("%d.%m.%Y"),
            activity=activity or "Nothing recorded yet.",
            emails=emails,
        )

        try:
            raw = self._ai(prompt)
            de_text, en_text = _split_bilingual(raw)
            if self._voice and self._voice.is_ready:
                if de_text:
                    self._voice._config["stt_active"] = "de"
                    self._voice.speak(de_text, blocking=True)
                if en_text:
                    self._voice._config["stt_active"] = "en"
                    self._voice.speak(en_text, blocking=True)
                self._voice._config["stt_active"] = "de"  # restore default
            else:
                print(f"[Schedule] Morning (no voice):\n  DE: {de_text}\n  EN: {en_text}")
        except Exception as e:
            print(f"[Schedule] Morning briefing error: {e}")

    # ── Evening farewell + shutdown ───────────────────────────────────────────

    def _do_farewell_and_shutdown(self) -> None:
        now = self._now_berlin()
        activity = self._collect_recent_activity(hours=16)

        prompt = _FAREWELL_PROMPT.format(
            time=now.strftime("%H:%M"),
            activity=activity or "A quiet day.",
        )

        try:
            raw = self._ai(prompt)
            de_text, en_text = _split_bilingual(raw)
            if self._voice and self._voice.is_ready:
                if de_text:
                    self._voice._config["stt_active"] = "de"
                    self._voice.speak(de_text, blocking=True)
                if en_text:
                    self._voice._config["stt_active"] = "en"
                    self._voice.speak(en_text, blocking=True)
                self._voice._config["stt_active"] = "de"
            else:
                print(f"[Schedule] Farewell (no voice):\n  DE: {de_text}\n  EN: {en_text}")
        except Exception as e:
            print(f"[Schedule] Farewell error: {e}")
            if self._voice and self._voice.is_ready:
                self._voice._config["stt_active"] = "de"
                self._voice.speak("Gute Nacht. Bis morgen früh.", blocking=True)
                self._voice._config["stt_active"] = "en"
                self._voice.speak("Good night. See you tomorrow.", blocking=True)

        # Set RTC wake alarm then shut down
        time.sleep(2)
        self._set_rtc_wakeup()
        time.sleep(1)
        self._do_shutdown()

    def _set_rtc_wakeup(self) -> None:
        """Set the RTC (hardware clock) alarm to wake the PC at the configured time."""
        wakeup_hm = self._cfg.get("wakeup_time", "08:00")
        wh, wm = map(int, wakeup_hm.split(":"))

        now = self._now_berlin()
        # Next morning: if already past wakeup time today, schedule for tomorrow
        wake_dt = now.replace(hour=wh, minute=wm, second=0, microsecond=0)
        if wake_dt <= now:
            wake_dt += timedelta(days=1)

        # Convert to UTC Unix timestamp for rtcwake
        import calendar
        ts = int(calendar.timegm(wake_dt.utctimetuple()))

        # rtcwake: set alarm, do NOT suspend now (-m no), use UTC timestamp
        cmd = f"sudo rtcwake -m no -u -t {ts}"
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if r.returncode == 0:
            print(f"[Schedule] RTC wake alarm set for {wake_dt.strftime('%Y-%m-%d %H:%M %Z')}")
        else:
            print(f"[Schedule] rtcwake failed: {r.stderr.strip()}")
            # Fallback: write a systemd timer or at job
            self._set_wakeup_fallback(wake_dt)

    def _set_wakeup_fallback(self, wake_dt: datetime) -> None:
        """Fallback: use systemd-run or 'at' command if rtcwake unavailable."""
        ts_str = wake_dt.strftime("%Y-%m-%d %H:%M:%S")
        # Try systemd-run for wake (only works on systems with systemd sleep)
        r = subprocess.run(
            f"sudo systemd-run --on-calendar='{ts_str}' /bin/true",
            shell=True, capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"[Schedule] Wakeup fallback also failed. Set alarm manually.")

    def _do_shutdown(self) -> None:
        """Shut down the system."""
        print("[Schedule] Initiating shutdown…")
        subprocess.run("sudo shutdown now", shell=True)

    # ── Context collectors ────────────────────────────────────────────────────

    def _collect_recent_activity(self, hours: int = 20) -> str:
        """Find all astraeus.json files modified in the last N hours and extract activity."""
        cutoff = time.time() - hours * 3600
        items: list[str] = []

        try:
            r = subprocess.run(
                f'find "{self._mem_root}" -name "astraeus.json" '
                f'-newer /proc/1 2>/dev/null',
                shell=True, capture_output=True, text=True, timeout=15,
            )
            # Also find by modification time
            r2 = subprocess.run(
                f'find "{self._mem_root}" /mnt /media -name "astraeus.json" 2>/dev/null',
                shell=True, capture_output=True, text=True, timeout=15,
            )
            files = set(
                l.strip() for l in (r.stdout + r2.stdout).splitlines() if l.strip()
            )
        except Exception:
            files = set()

        for fpath in files:
            p = Path(fpath)
            try:
                if p.stat().st_mtime < cutoff:
                    continue
                data = json.loads(p.read_text())
                log = data.get("recent_activity", [])
                folder = Path(data.get("folder", p.parent)).name
                notes = data.get("ai_notes", "")
                for entry in log[:5]:
                    ts = entry.get("timestamp", "")[:16].replace("T", " ")
                    act = entry.get("action", "")
                    if act:
                        items.append(f"[{folder}] {act}")
            except Exception:
                continue

        if not items:
            return ""
        # Return up to 8 most recent items, deduplicated
        seen = set()
        unique = []
        for item in items:
            if item not in seen:
                seen.add(item)
                unique.append(item)
        return "\n".join(unique[:8])

    def _check_email_count(self) -> str:
        """Try to get an email count without the full IMAP fetch."""
        cfg_path = Path.home() / ".config" / "astraeus" / "email.json"
        if not cfg_path.exists():
            return "Email not configured."
        try:
            import imaplib
            cfg = json.loads(cfg_path.read_text())
            ic = cfg.get("imap", {})
            mail = imaplib.IMAP4_SSL(ic["host"], int(ic.get("port", 993)))
            mail.login(ic["username"], ic["password"])
            mail.select("INBOX")
            today = datetime.now().strftime("%d-%b-%Y")
            _, data = mail.search(None, f'(SINCE "{today}" UNSEEN)')
            count = len(data[0].split()) if data[0] else 0
            mail.close()
            mail.logout()
            if count == 0:
                return "No new emails today."
            return f"{count} unread email{'s' if count > 1 else ''} today."
        except Exception:
            return "Email check skipped."

    # ── Config helpers ────────────────────────────────────────────────────────

    def set_times(self, shutdown: str, wakeup: str) -> None:
        """e.g. set_times('00:00', '08:00')"""
        self._cfg["shutdown_time"] = shutdown
        self._cfg["wakeup_time"] = wakeup
        self.save_config()

    def set_enabled(self, enabled: bool) -> None:
        self._cfg["enabled"] = enabled
        self.save_config()

    def set_language(self, lang: str) -> None:
        """'Deutsch', 'English', or 'auto'"""
        self._cfg["language"] = lang
        self.save_config()


# ── Module helpers ────────────────────────────────────────────────────────────

def _weekday_name(dt: datetime, lang: str) -> str:
    de = ["Montag","Dienstag","Mittwoch","Donnerstag","Freitag","Samstag","Sonntag"]
    en = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
    names = de if "Deutsch" in lang or lang == "de" else en
    return names[dt.weekday()]


def _split_bilingual(text: str) -> tuple[str, str]:
    """
    Parse AI output formatted as:
      [DE] German text here
      [EN] English text here
    Returns (de_text, en_text). Falls back gracefully if format is missing.
    """
    import re
    de_match = re.search(r'\[DE\]\s*(.+?)(?=\[EN\]|$)', text, re.DOTALL | re.IGNORECASE)
    en_match = re.search(r'\[EN\]\s*(.+?)$', text, re.DOTALL | re.IGNORECASE)
    de_text = _clean_ai_output(de_match.group(1)) if de_match else ""
    en_text = _clean_ai_output(en_match.group(1)) if en_match else ""
    # If the AI ignored the format, use the whole text for both
    if not de_text and not en_text:
        cleaned = _clean_ai_output(text)
        return cleaned, cleaned
    return de_text, en_text


def _clean_ai_output(text: str) -> str:
    """Strip XML tags, markdown, tool calls from AI output before TTS."""
    import re
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'`[^`]+`', '', text)
    text = re.sub(r'[*_#>|]+', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()
