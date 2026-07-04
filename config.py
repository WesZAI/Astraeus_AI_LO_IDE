# ==========================================
# Copyright (c) 2026 Gabriela Berger AI Oberland
# All Rights Reserved.
# This code is subject to the custom NON-COMMERCIAL 
# & ANTI-CORPORATE LICENSE (Maximum 20 PCs) found in the LICENSE file.
# ==========================================
# config.py
# NUR die von dir gewünschten lokalen Modelle
# Alle Cloud-Modelle entfernt, ROCm regelt GPU/CPU-Verteilung automatisch
import os
import shutil
from dataclasses import dataclass


@dataclass
class ModelConfig:
    name: str
    command: str
    host: str
    port: int
    endpoint_type: str = "chat"
    api_key_env: str = ""
    model_id: str = ""
    base_url: str = ""
    use_n_predict: bool = False


@dataclass
class AgentConfig:
    name: str
    command: str
    workdir: str


def _find_llama_server() -> str:
    if env := os.environ.get("ASTRAEUS_LLAMA_BIN"):
        return env
    if found := shutil.which("llama-server"):
        return found
    candidates = [
        "../llama.cpp/build/bin/llama-server",
        os.path.expanduser("~/llama.cpp/build/bin/llama-server"),
        "/usr/local/bin/llama-server",
        "/opt/llama.cpp/build/bin/llama-server",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return "llama-server"


def _find_models_dir() -> str:
    if env := os.environ.get("ASTRAEUS_MODELS_DIR"):
        return env
    candidates = [
        "../models",
        os.path.expanduser("~/models"),
        os.path.expanduser("~/IDE"),
    ]
    for path in candidates:
        if os.path.isdir(path):
            return path
    return os.path.expanduser("~/models")


def _find_companion_dir() -> str:
    # astraeus.gguf liegt in einem separaten Ordner
    if env := os.environ.get("ASTRAEUS_COMPANION_DIR"):
        return env
    candidates = [
        "../Astraeus_companion",
        os.path.expanduser("~/Astraeus_companion"),
    ]
    for path in candidates:
        if os.path.isdir(path):
            return path
    return _find_models_dir()


LLAMA_SERVER = _find_llama_server()
MODELS_DIR = _find_models_dir()
COMPANION_DIR = _find_companion_dir()

# LD_LIBRARY_PATH prefix so shared libs (libmtmd.so etc.) next to the binary are found
_lib_dir = os.path.dirname(LLAMA_SERVER)
_LD_PREFIX = f"LD_LIBRARY_PATH={_lib_dir}:$LD_LIBRARY_PATH "


class AppConfig:
    def __init__(self):
        self.models = {
            "Large-Model-120B": ModelConfig(
                name="Large-Model-120B",
                command=f"./start_master.sh {MODELS_DIR}/large_model.gguf 65536 none --mmproj-auto",
                host="127.0.0.1",
                port=8081,
                endpoint_type="chat",
            ),
            "Small-Model-8B": ModelConfig(
                name="Small-Model-8B",
                command=f"./start_master.sh {MODELS_DIR}/small_model.gguf 8192 chatml --mmproj-auto",
                host="127.0.0.1",
                port=8081,
                endpoint_type="chat",
                use_n_predict=True,
            )
        }/Mistral-Medium-3.5-128B-Q3_K_M-00001-of-00003.gguf 131072 none --mmproj-auto",
                host="127.0.0.1",
                port=8081,
                endpoint_type="chat",
            ),
            "Astraeus_F16": ModelConfig(
                name="Astraeus_F16",
                command=f"./start_master.sh {COMPANION_DIR}/Astraeus_F16.gguf 32768 none --mmproj-auto",
                host="127.0.0.1",
                port=8081,
                endpoint_type="legacy",
            ),
            "gemini_f16": ModelConfig(
                name="gemini_f16",
                command=f"./start_master.sh {MODELS_DIR}/gemini_f16.gguf 32768 none --mmproj-auto",
                host="127.0.0.1",
                port=8081,
                endpoint_type="legacy",
            ),
            "Devstral-Small-2-24B-Instruct-2512-UD-Q8_K_XL": ModelConfig(
                name="Devstral-Small-2-24B-Instruct-2512-UD-Q8_K_XL",
                command=f"./start_master.sh {MODELS_DIR}/Devstral-Small-2-24B-Instruct-2512-UD-Q8_K_XL.gguf 131072 chatml --mmproj-auto",
                host="127.0.0.1",
                port=8081,
                endpoint_type="chat",
                use_n_predict=True,
            ),
            "gemma-4-31B-it-UD-Q8_K_XL": ModelConfig(
                name="gemma-4-31B-it-UD-Q8_K_XL",
                command=f"./start_master.sh {MODELS_DIR}/gemma-4-31B-it-UD-Q8_K_XL.gguf 65536 none --mmproj-auto",
                host="127.0.0.1",
                port=8081,
                endpoint_type="chat",
            ),
            "Mistral-Small-3.2-24B-Instruct-2506-UD-Q8_K_XL": ModelConfig(
                name="Mistral-Small-3.2-24B-Instruct-2506-UD-Q8_K_XL",
                command=f"./start_master.sh {MODELS_DIR}/Mistral-Small-3.2-24B-Instruct-2506-UD-Q8_K_XL.gguf 65536 chatml --mmproj-auto",
                host="127.0.0.1",
                port=8081,
                endpoint_type="chat",
                use_n_predict=True,
            ),
            "mistral-7b-v0.1.Q8_0": ModelConfig(
                name="mistral-7b-v0.1.Q8_0",
                command=f"./start_master.sh {MODELS_DIR}/mistral-7b-v0.1.Q8_0.gguf 65536 none --mmproj-auto",
                host="127.0.0.1",
                port=8081,
                endpoint_type="chat",
            ),
        }

        self.agents = {
            "IDEAgent": AgentConfig(
                name="IDEAgent",
                command="python3 ide_agent.py",
                workdir=os.path.dirname(os.path.abspath(__file__)),
            )
        }
