# ==========================================
# Copyright (c) 2026 Gabriela Berger AI Oberland
# All Rights Reserved.
# This code is subject to the custom NON-COMMERCIAL 
# & ANTI-CORPORATE LICENSE (Maximum 20 PCs) found in the LICENSE file.
# ==========================================
"""astraeus_voice.py — Offline voice I/O for Astraeus.

STT : faster-whisper — https://github.com/SYSTRAN/faster-whisper
TTS : Piper          — https://github.com/rhasspy/piper

No OpenAI API. No cloud. Runs 100% offline.

━━━ ONE-TIME SETUP ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Install dependencies:
  pip3 install faster-whisper sounddevice numpy piper-tts --break-system-packages

STT model is downloaded automatically on first use from HuggingFace.
  Default: medium (~1.5 GB, best quality/speed trade-off for German)
  Fastest: base   (~145 MB)
  Best:    large-v3 (~3 GB)
  Set "stt_model_size" in voice_config.json to change.

Download TTS voice — MALE VOICES ONLY (calm, deep):
  German  : de_DE-thorsten_emotional-medium.onnx       ← recommended
  English : en_US-joe-medium.onnx                     ← calm male
  https://huggingface.co/rhasspy/piper-voices/tree/main
  Download both the .onnx file AND the .onnx.json config file.

Save .onnx files to the IDE directory or ~/.config/astraeus/
Config file is auto-created at: ~/.config/astraeus/voice_config.json
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Callable, Optional

# ── Optional imports ──────────────────────────────────────────────────────────
try:
    import numpy as np
    _NUMPY = True
except ImportError:
    _NUMPY = False

try:
    import sounddevice as sd
    _SD = True
except ImportError:
    _SD = False

try:
    from faster_whisper import WhisperModel
    _WHISPER = True
except ImportError:
    _WHISPER = False

try:
    from piper import PiperVoice
    _PIPER_PY = True
except ImportError:
    _PIPER_PY = False

# Use ~/.local/bin/piper (real piper-tts) not /usr/bin/piper (PipeWire GTK app)
def _find_piper_bin() -> Optional[str]:
    local = Path.home() / ".local" / "bin" / "piper"
    if local.exists():
        return str(local)
    found = shutil.which("piper")
    if found and found != "/usr/bin/piper":
        return found
    return None

_PIPER_BIN = _find_piper_bin()

# ── Voice states ──────────────────────────────────────────────────────────────
class VoiceState:
    IDLE         = "idle"
    LISTENING    = "listening"
    TRANSCRIBING = "transcribing"
    SPEAKING     = "speaking"
    ERROR        = "error"

STATE_UI = {
    VoiceState.IDLE:         ("",                "#888888"),
    VoiceState.LISTENING:    ("● Listening…",    "#ff6b6b"),
    VoiceState.TRANSCRIBING: ("⟳ Transcribing…", "#f0a500"),
    VoiceState.SPEAKING:     ("◆ Speaking…",     "#7ed07e"),
    VoiceState.ERROR:        ("✗ Voice Error",   "#ff4444"),
}

_DEFAULT_CONFIG_PATH = Path.home() / ".config" / "astraeus" / "voice_config.json"
_DEFAULT_MODELS_DIR  = Path(os.environ.get("ASTRAEUS_VOICE_MODELS", str(Path(__file__).parent)))

# ── Language detection ────────────────────────────────────────────────────────
_DE_CHARS = set('äöüÄÖÜß')
_DE_WORDS = {
    'der', 'die', 'das', 'ein', 'eine', 'ich', 'ist', 'nicht', 'mit',
    'auf', 'für', 'und', 'oder', 'aber', 'wenn', 'dann', 'auch', 'noch',
    'wie', 'was', 'wir', 'sie', 'haben', 'sein', 'werden', 'kann', 'wird',
    'beim', 'vom', 'zur', 'zum', 'im', 'am', 'dem', 'den', 'des', 'bei',
    'nach', 'vor', 'über', 'unter', 'hier', 'bitte', 'danke', 'ja', 'nein',
    'schreib', 'mach', 'öffne', 'zeig', 'suche', 'erstelle', 'installiere',
}
_EN_WORDS = {
    'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'will',
    'have', 'this', 'that', 'with', 'from', 'they', 'been', 'when', 'there',
    'your', 'what', 'which', 'would', 'could', 'should', 'please', 'write',
    'make', 'open', 'show', 'search', 'create', 'install', 'find', 'run',
}

def _detect_language(text: str) -> str:
    import re as _r
    lower = text.lower()
    de_char_score = sum(1 for c in text if c in _DE_CHARS) * 2
    words = set(_r.findall(r'\b[a-zA-ZäöüÄÖÜß]{2,}\b', lower))
    de_score = de_char_score + len(words & _DE_WORDS)
    en_score = len(words & _EN_WORDS)
    return 'de' if de_score >= en_score else 'en'


_DEFAULT_CONFIG = {
    # ── STT (faster-whisper) ─────────────────────────────────────────────────
    # model_size: tiny | base | small | medium | large-v2 | large-v3
    # Downloaded automatically from HuggingFace on first use.
    # base = ~145 MB, fast, good quality.  medium = ~1.5 GB, best for German.
    "stt_model_size": "base",
    "stt_device": "cpu",        # "cpu" or "cuda"
    "stt_compute_type": "int8", # "int8" (cpu) | "float16" (cuda)
    "stt_active": "de",         # "de" or "en" — toggled by DE/EN button in GUI

    # ── TTS voices — MALE ONLY, calm and deep ────────────────────────────────
    "tts_de": {
        "model_path": str(_DEFAULT_MODELS_DIR / "de_DE-thorsten_emotional-medium.onnx"),
        "length_scale": 1.15,
        "noise_scale": 0.333,
        "noise_w": 0.8,
    },
    "tts_en": {
        "model_path": str(_DEFAULT_MODELS_DIR / "en_US-joe-medium.onnx"),
        "length_scale": 1.1,
        "noise_scale": 0.333,
        "noise_w": 0.8,
    },

    # ── Voice activity detection ─────────────────────────────────────────────
    "vad": {
        "silence_threshold_rms": 600,
        "silence_duration_sec": 1.5,
        "max_listen_sec": 30.0,
    },
}


class VoiceEngine:
    """
    Manages microphone recording (faster-whisper STT) and speech synthesis (Piper TTS).
    All hardware operations run in daemon threads so Tkinter stays responsive.
    """

    def __init__(self, config_path: str | None = None):
        self._cfg_path = Path(config_path or _DEFAULT_CONFIG_PATH)
        self._config: dict = {}
        self._whisper: Optional[WhisperModel] = None
        self._piper_de = None
        self._piper_en = None
        self._listening = False
        self._speaking = False
        self._stop_speech = threading.Event()
        self._listen_thread: Optional[threading.Thread] = None
        self._speak_thread: Optional[threading.Thread] = None
        self._on_state: Optional[Callable[[str], None]] = None
        self._load_config()

    # ── Setup ─────────────────────────────────────────────────────────────────

    def _load_config(self) -> None:
        if self._cfg_path.exists():
            try:
                self._config = json.loads(self._cfg_path.read_text())
                return
            except Exception:
                pass
        self._config = json.loads(json.dumps(_DEFAULT_CONFIG))

    def save_config(self) -> None:
        self._cfg_path.parent.mkdir(parents=True, exist_ok=True)
        self._cfg_path.write_text(json.dumps(self._config, indent=2))

    def set_state_callback(self, cb: Callable[[str], None]) -> None:
        self._on_state = cb

    def _set_state(self, state: str) -> None:
        if self._on_state:
            try:
                self._on_state(state)
            except Exception:
                pass

    def check_dependencies(self) -> list[str]:
        issues = []
        if not _NUMPY:
            issues.append("numpy missing:          pip3 install numpy --break-system-packages")
        if not _SD:
            issues.append("sounddevice missing:    pip3 install sounddevice --break-system-packages")
        if not _WHISPER:
            issues.append("faster-whisper missing: pip3 install faster-whisper --break-system-packages")
        if not _PIPER_PY and not _PIPER_BIN:
            issues.append("piper missing:          pip3 install piper-tts --break-system-packages")

        de_tts = Path(self._config.get("tts_de", {}).get("model_path", "")).expanduser()
        en_tts = Path(self._config.get("tts_en", {}).get("model_path", "")).expanduser()
        if not de_tts.exists():
            issues.append(
                f"German TTS voice missing: {de_tts}\n"
                f"  → de_DE-thorsten_emotional-medium.onnx + .onnx.json\n"
                f"  → https://huggingface.co/rhasspy/piper-voices"
            )
        if not en_tts.exists():
            issues.append(
                f"English TTS voice missing: {en_tts}\n"
                f"  → en_US-joe-medium.onnx + .onnx.json\n"
                f"  → https://huggingface.co/rhasspy/piper-voices"
            )
        return issues

    def setup(self) -> tuple[bool, str]:
        """
        Load the Whisper STT model and both Piper TTS voices.
        Returns (success, message).
        """
        if not _NUMPY or not _SD or not _WHISPER or (not _PIPER_PY and not _PIPER_BIN):
            missing = self.check_dependencies()
            return False, "\n".join(missing)

        loaded = []
        errors = []

        # STT — faster-whisper (single multilingual model handles DE + EN)
        try:
            size = self._config.get("stt_model_size", "medium")
            device = self._config.get("stt_device", "cpu")
            compute = self._config.get("stt_compute_type", "int8")
            print(f"[Voice] Loading Whisper {size} ({device}/{compute}) — may download on first run…")
            self._whisper = WhisperModel(size, device=device, compute_type=compute)
            loaded.append(f"STT-Whisper-{size}")
        except Exception as e:
            errors.append(f"Whisper: {e}")

        if _PIPER_PY:
            try:
                p = str(Path(self._config["tts_de"]["model_path"]).expanduser())
                if Path(p).exists():
                    self._piper_de = PiperVoice.load(p, use_cuda=False)
                    loaded.append("TTS-DE")
            except Exception as e:
                errors.append(f"TTS-DE: {e}")

            try:
                p = str(Path(self._config["tts_en"]["model_path"]).expanduser())
                if Path(p).exists():
                    self._piper_en = PiperVoice.load(p, use_cuda=False)
                    loaded.append("TTS-EN")
            except Exception as e:
                errors.append(f"TTS-EN: {e}")

        has_stt = self._whisper is not None
        has_tts = self._piper_de is not None or self._piper_en is not None or _PIPER_BIN

        if not has_stt or not has_tts:
            return False, "Incomplete: " + ", ".join(errors)

        msg = f"Voice ready: {', '.join(loaded)}"
        if errors:
            msg += f"  (warnings: {'; '.join(errors)})"
        return True, msg

    @property
    def is_ready(self) -> bool:
        has_tts = self._piper_de is not None or self._piper_en is not None or bool(_PIPER_BIN)
        return self._whisper is not None and has_tts

    def set_stt_language(self, lang: str) -> None:
        if lang in ("de", "en"):
            self._config["stt_active"] = lang
            self.save_config()

    @property
    def is_listening(self) -> bool:
        return self._listening

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    # ── STT ───────────────────────────────────────────────────────────────────

    def listen_async(
        self,
        on_result: Callable[[str], None],
        on_partial: Optional[Callable[[str], None]] = None,
    ) -> None:
        if self._listening:
            return
        self._listen_thread = threading.Thread(
            target=self._listen_worker,
            args=(on_result, on_partial),
            daemon=True,
            name="astraeus-stt",
        )
        self._listen_thread.start()

    def stop_listening(self) -> None:
        self._listening = False

    def _listen_worker(
        self,
        on_result: Callable[[str], None],
        on_partial: Optional[Callable[[str], None]],
    ) -> None:
        if not self._whisper or not _SD or not _NUMPY:
            self._set_state(VoiceState.ERROR)
            on_result("")
            return

        cfg_vad = self._config["vad"]
        sample_rate = 16000
        chunk_size = 4000
        rms_thresh: int = cfg_vad.get("silence_threshold_rms", 600)
        silence_sec: float = cfg_vad.get("silence_duration_sec", 1.5)
        max_sec: float = cfg_vad.get("max_listen_sec", 30.0)
        silence_frames_needed = int(silence_sec * sample_rate / chunk_size)

        audio_data = bytearray()
        speech_started = False
        silence_frames = 0
        self._listening = True
        self._set_state(VoiceState.LISTENING)

        try:
            with sd.RawInputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="int16",
                blocksize=chunk_size,
            ) as stream:
                deadline = time.monotonic() + max_sec
                while self._listening and time.monotonic() < deadline:
                    raw, _ = stream.read(chunk_size)
                    raw_bytes = bytes(raw)
                    samples = np.frombuffer(raw_bytes, dtype=np.int16)
                    rms = int(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))

                    if rms > rms_thresh:
                        speech_started = True
                        silence_frames = 0
                        audio_data.extend(raw_bytes)
                        if on_partial:
                            on_partial("…")
                    elif speech_started:
                        audio_data.extend(raw_bytes)
                        silence_frames += 1
                        if silence_frames >= silence_frames_needed:
                            break
        except Exception as e:
            print(f"[Voice] listen error: {e}")
            self._set_state(VoiceState.ERROR)
            on_result("")
            return
        finally:
            self._listening = False

        if not speech_started or not audio_data:
            self._set_state(VoiceState.IDLE)
            on_result("")
            return

        self._set_state(VoiceState.TRANSCRIBING)
        try:
            lang = self._config.get("stt_active", "de")
            audio_np = np.frombuffer(bytes(audio_data), dtype=np.int16).astype(np.float32) / 32768.0
            segments, _ = self._whisper.transcribe(
                audio_np,
                language=lang,
                beam_size=5,
                vad_filter=True,
            )
            text = " ".join(s.text for s in segments).strip()
        except Exception as e:
            print(f"[Voice] transcribe error: {e}")
            text = ""

        self._set_state(VoiceState.IDLE)
        on_result(text)

    # ── TTS ───────────────────────────────────────────────────────────────────

    def speak(self, text: str, blocking: bool = False, on_done: Optional[Callable] = None) -> None:
        text = text.strip()
        if not text:
            return
        self.stop_speaking()
        self._stop_speech.clear()
        self._speak_thread = threading.Thread(
            target=self._speak_worker,
            args=(text, on_done),
            daemon=True,
            name="astraeus-tts",
        )
        self._speak_thread.start()
        if blocking:
            self._speak_thread.join()

    def stop_speaking(self) -> None:
        self._stop_speech.set()
        try:
            sd.stop()
        except Exception:
            pass
        self._speaking = False

    def _speak_worker(self, text: str, on_done: Optional[Callable]) -> None:
        self._speaking = True
        self._set_state(VoiceState.SPEAKING)
        try:
            lang = _detect_language(text)
            if _PIPER_PY:
                voice = self._piper_de if lang == "de" else self._piper_en
                if voice is None:
                    voice = self._piper_de or self._piper_en
                if voice:
                    cfg_key = f"tts_{lang}" if lang in ("de", "en") else "tts_de"
                    self._speak_piper_py(text, voice, self._config.get(cfg_key, {}))
                    return
            if _PIPER_BIN:
                cfg_key = f"tts_{lang}" if lang in ("de", "en") else "tts_de"
                self._speak_piper_cli(text, self._config.get(cfg_key, {}))
            else:
                print("[Voice] No TTS engine available.")
        except Exception as e:
            print(f"[Voice] TTS error: {e}")
        finally:
            self._speaking = False
            self._set_state(VoiceState.IDLE)
            if on_done:
                try:
                    on_done()
                except Exception:
                    pass

    def _speak_piper_py(self, text: str, voice, cfg: dict) -> None:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            voice.synthesize(
                text, wf,
                length_scale=cfg.get("length_scale", 1.1),
                noise_scale=cfg.get("noise_scale", 0.333),
                noise_w=cfg.get("noise_w", 0.8),
            )
        buf.seek(0)
        with wave.open(buf, "rb") as wf:
            rate = wf.getframerate()
            raw = wf.readframes(wf.getnframes())
        if not raw:
            return
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        sd.play(samples, samplerate=rate)
        while sd.get_stream().active and not self._stop_speech.is_set():
            time.sleep(0.05)
        sd.stop()

    def _speak_piper_cli(self, text: str, cfg: dict) -> None:
        model = str(Path(cfg.get("model_path", "")).expanduser())
        length_scale = cfg.get("length_scale", 1.1)
        noise_scale = cfg.get("noise_scale", 0.333)
        safe_text = text.replace("'", '"')
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp = f.name
        try:
            subprocess.run(
                f"echo '{safe_text}' | '{_PIPER_BIN}' --model '{model}' "
                f"--length_scale {length_scale} --noise_scale {noise_scale} "
                f"--output_file '{tmp}'",
                shell=True, capture_output=True, timeout=30,
            )
            if not Path(tmp).exists() or Path(tmp).stat().st_size == 0:
                return
            with wave.open(tmp, "rb") as wf:
                rate = wf.getframerate()
                raw = wf.readframes(wf.getnframes())
            if not raw:
                return
            samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            sd.play(samples, samplerate=rate)
            while sd.get_stream().active and not self._stop_speech.is_set():
                time.sleep(0.05)
            sd.stop()
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass

    # ── Config helpers ────────────────────────────────────────────────────────

    def set_stt_model_size(self, size: str) -> None:
        self._config["stt_model_size"] = size
        self.save_config()

    def set_silence_threshold(self, rms: int) -> None:
        self._config["vad"]["silence_threshold_rms"] = rms
        self.save_config()
