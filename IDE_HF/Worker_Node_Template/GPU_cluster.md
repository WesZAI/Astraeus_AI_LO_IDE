🚀 Setup-Guide: Lokales 72GB Offline KI-Cluster
Diese Dokumentation beschreibt die Einrichtung eines vollständig lokalen, offline-fähigen KI-Clusters mit llama.cpp. Das System bündelt den VRAM von bis zu 5 Rechnern (dynamisch zuschaltbar) und stellt eine OpenAI-kompatible API für KI-Agenten zur Verfügung.

🏗 Architektur-Übersicht
Master-Node (Linux, RX 7900 - 24GB): Steuert das Cluster, lädt das Modell und stellt den API-Endpunkt für die Agenten bereit. (IP-Beispiel: 10.0.0.1)
Worker 1 (Windows, RTX 5070 Ti - 16GB): Tag & Nacht verfügbar. (IP: 10.0.0.2)
Worker 2 (Linux, RTX 3080 - 8GB): Tag & Nacht verfügbar. (IP: 10.0.0.3)
Nacht-Worker 3 (z.B. User1 - 8GB): Nur nachts verfügbar. (IP: 10.0.0.4)
Nacht-Worker 4 (z.B. User2 - 16GB): Nur nachts verfügbar. (IP: 10.0.0.5)
🛠 Phase 1: Vorbereitungen im Netzwerk
Statische IPs: Vergib im Router (z. B. FritzBox) für alle 5 PCs eine feste IPv4-Adresse, damit die Skripte immer funktionieren.
Llama.cpp herunterladen: Lade für jeden PC die passende kompilierte Release-Version von llama.cpp (CUDA für Nvidia, ROCm/Vulkan für AMD) herunter und entpacke sie.
Netcat installieren (Nur Master): Führe auf dem Master-Linux-PC sudo apt-get install netcat aus. Dies wird für den dynamischen Netzwerk-Scan benötigt.
💻 Phase 2: Einrichtung der Worker-Knoten
Auf den 4 Helfer-PCs muss lediglich ein Skript gestartet werden, das die Grafikkarte im Netzwerk zur Verfügung stellt.

Für Windows-Worker (PowerShell)
Erstelle auf den Windows-Rechnern eine Datei namens start_worker.ps1. Passe den Pfad und den jeweiligen Port (z.B. 50052) an.

'''
powershell
Get-ChildItem -Path C:\ -Filter "rpc-server.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object DirectoryName
'''
powershell
$LlamaPath = "C:\Path\To\llama-b8871-bin-win-cuda-13.1-x64"
$Port = 50052 # Für jeden PC einen eigenen Port wählen (50052, 50054, etc.)

Write-Host "Starte Llama RPC Worker auf Port $Port..." -ForegroundColor Cyan
Set-Location -Path $LlamaPath

$RpcFile = Get-ChildItem -Filter "rpc-server.exe*" -File -ErrorAction SilentlyContinue | Select-Object -First 1

if ($RpcFile) {
    Write-Host "Datei gefunden: $($RpcFile.Name) - Starte Server..." -ForegroundColor Green
    & ".\$($RpcFile.Name)" -H 0.0.0.0 -p $Port
} else {
    Write-Host "Fehler: llama-rpc-server nicht gefunden im Ordner $LlamaPath!" -ForegroundColor Red
    Write-Host "=============================================" -ForegroundColor Yellow
    Write-Host "Das ist der tatsächliche Inhalt dieses Ordners:" -ForegroundColor Yellow
    Get-ChildItem | Select-Object Name
    exit 1
}
´´´
pwsh
.\start_worker.ps1
```

Tipp: Ggf. musst du Skripte in Windows erlauben, indem du einmalig Set-ExecutionPolicy RemoteSigned -Scope CurrentUser in einer als Administrator geöffneten PowerShell ausführst.

Für Linux-Worker (Bash)
Erstelle auf dem Linux-Rechner eine Datei namens start_worker.sh und mache sie ausführbar (chmod +x start_worker.sh).

cd /path/to/your/llama.cpp
cmake -B build -DGGML_RPC=ON
cmake --build --config Release

bash start_worker.sh

bash
#!/bin/bash
# start_worker.sh

LLAMA_DIR="/path/to/your/llama.cpp/build/bin"
PORT=50053

echo "Starte Llama RPC Worker auf Port $PORT..."
cd "$LLAMA_DIR" || exit 1

./llama-rpc-server -H 0.0.0.0 -p $PORT
🧠 Phase 3: Der Master-Knoten (Auto-Discovery)
Dieses Skript läuft auf dem Master (RX 7900). Es prüft dynamisch, ob die Nacht-PCs erreichbar sind, und baut das Cluster entsprechend auf.

Erstelle start_master.sh und mache es ausführbar (chmod +x start_master.sh):

cd /path/to/your/llama.cpp
cmake -B build -DGGML_RPC=ON
cmake --build --config Release
cd /build/bin/rpc-server
bash start_master.sh


bash
#!/bin/bash
# start_master.sh

LLAMA_DIR="/path/to/your/llama.cpp/build/bin"
MODEL_PATH="/path/to/your/modelle/dein-70b-modell.gguf"

# 1. Definieren der verfügbaren Rechner (IPs anpassen!)
WORKER_1="10.0.0.2:50052" # RTX 5070 Ti (Tag)
WORKER_2="10.0.0.3:50053" # RTX 3080 (Tag)
WORKER_NIGHT_1="10.0.0.4:50054" # User1 PC (Nacht)
WORKER_NIGHT_2="10.0.0.5:50055" # User2 PC (Nacht)

RPC_NODES=""

# Hilfsfunktion zum sauberen Anfügen an den String
add_node() {
    if [ -z "$RPC_NODES" ]; then
        RPC_NODES="$1"
    else
        RPC_NODES="$RPC_NODES,$1"
    fi
}

echo "🔍 Prüfe verfügbare Worker im Netzwerk..."

# Tag-PCs sind immer an
add_node "$WORKER_1"
add_node "$WORKER_2"

# Prüfe Nacht-PC 1 (Timeout 1 Sekunde)
if nc -z -w 1 10.0.0.4 50054 >/dev/null 2>&1; then
    echo "[+] Nacht-Worker 1 gefunden! Füge 16GB VRAM hinzu."
    add_node "$WORKER_NIGHT_1"
fi

# Prüfe Nacht-PC 2
if nc -z -w 1 10.0.0.5 50055 >/dev/null 2>&1; then
    echo "[+] Nacht-Worker 2 gefunden! Füge 8GB VRAM hinzu."
    add_node "$WORKER_NIGHT_2"
fi

echo "========================================="
echo "🚀 Starte Master Server"
echo "Eingebundene Knoten: $RPC_NODES"
echo "========================================="

cd "$LLAMA_DIR" || exit 1

./llama-server \
    -m "/path/to/your/model/Astraeus.gguf" \
    -c 32768 \
    -ngl 99 \
    --rpc "$RPC_NODES" \
    --host 0.0.0.0 \
    --port 8081
🤖 Phase 4: Agenten-Anbindung
Da der `llama-server` eine vollständig OpenAI-kompatible API bereitstellt, kannst du nun jeden beliebigen Agenten (z. B. OpenClaw, OpenDevin, AutoGPT) direkt mit deinem lokalen Cluster verbinden.

Konfiguriere deinen Agenten einfach mit folgenden Parametern:
*   **API Base URL / Endpoint:** `http://10.0.0.1:8081/v1` (IP deines Master-PCs)
*   **API Key:** `sk-irrelevant` (Kann ein beliebiger Text sein, llama.cpp ignoriert ihn)
*   **Model Name:** `llama-3.3-70b` (Je nachdem, was du geladen hast)

🕹 Phase 5: Täglicher Workflow
Der Start deines Systems ist nun extrem strukturiert und einfach:

Worker einschalten: Starte die start_worker-Skripte auf den Helfer-PCs (abends inkl. User1s/User2s PC).
Master hochfahren: Führe start_master.sh auf dem Haupt-Linux-PC aus. Es erkennt sofort, wer wach ist, und spannt das KI-Netzwerk auf.
Agenten starten: Starte dein bevorzugtes Agenten-Framework (Docker, Python-Skript etc.).
Genießen: Lass deinen Agenten autonom und komplett offline mit der Power von bis zu 72 GB VRAM arbeiten!


Den 3070 Ti reparieren
  git clone https://github.com/ggml-org/llama.cpp
  cd llama.cpp
  git checkout 3003c82f
  mkdir build && cd build
  cmake .. -DGGML_CUDA=ON -DGGML_RPC=ON -DCMAKE_BUILD_TYPE=Release
  make -j$(nproc) llama-rpc-server

