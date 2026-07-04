#!/bin/bash
# start_master.sh  — universeller RPC-Master für alle Modelle
#
# Verwendung:
#   start_master.sh <model_path> [context] [chat_template]
#
# Beispiele:
#   start_master.sh ../models/model.gguf 32768
#   start_master.sh ../models/model.gguf 131072 chatml

export HIP_VISIBLE_DEVICES="0"

# ── Argumente ──────────────────────────────────────────────────────────────────
MODEL_PATH="${1:-../models/model.gguf}"
CONTEXT="${2:-32768}"
CHAT_TEMPLATE="${3:-none}"

shift 3 || true
EXTRA_ARGS="$@"

LLAMA_DIR="../llama.cpp/build/bin"

# ── Worker-Tabelle: "ip:port:vram_gb" ─────────────────────────────────────────
WORKERS=(
    # Add your worker nodes here in the format "IP:PORT:VRAM_GB"
    # Example:
    # "192.168.1.100:50051:24" # Master RPC Node (24GB)
    # "192.168.1.101:50052:16" # Worker 1 (16GB)
)

echo "🔍 Prüfe alle Worker..."

AVAILABLE=()
for entry in "${WORKERS[@]}"; do
    ip="${entry%%:*}"
    rest="${entry#*:}"
    port="${rest%%:*}"
    vram="${rest##*:}"
    if nc -z -w 1 "$ip" "$port" >/dev/null 2>&1; then
        echo "[+] $ip:$port erreichbar (${vram}GB)"
        AVAILABLE+=("$vram:$ip:$port")
    else
        echo "[-] $ip:$port nicht erreichbar"
    fi
done

if [ ${#AVAILABLE[@]} -eq 0 ]; then
    echo "❌ Keine Worker gefunden — starte lokal ohne RPC."
    RPC_FLAG=""
else
    # Sortiere nach VRAM absteigend (größte GPU zuerst)
    IFS=$'\n' SORTED=($(sort -t: -k1 -rn <<< "${AVAILABLE[*]}"))
    unset IFS

    RPC_NODES=""
    echo ""
    echo "📊 Worker-Reihenfolge nach VRAM:"
    for entry in "${SORTED[@]}"; do
        vram="${entry%%:*}"
        rest="${entry#*:}"
        ip="${rest%%:*}"
        port="${rest##*:}"
        echo "   ${vram}GB -> $ip:$port"
        [ -z "$RPC_NODES" ] && RPC_NODES="$ip:$port" || RPC_NODES="$RPC_NODES,$ip:$port"
    done
    RPC_FLAG="--rpc $RPC_NODES"
fi

# ── Chat-Template Flag ─────────────────────────────────────────────────────────
TEMPLATE_FLAG=""
if [ "$CHAT_TEMPLATE" != "none" ] && [ -n "$CHAT_TEMPLATE" ]; then
    TEMPLATE_FLAG="--chat-template $CHAT_TEMPLATE"
fi

echo ""
echo "========================================="
echo "🚀 Starte Master Server"
echo "Modell:       $(basename "$MODEL_PATH")"
echo "Kontext:      $CONTEXT"
echo "RPC:          ${RPC_NODES:-keine Worker}"
echo "Template:     ${CHAT_TEMPLATE:-standard}"
echo "========================================="

cd "$LLAMA_DIR" || exit 1

./llama-server \
    -m "$MODEL_PATH" \
    -c "$CONTEXT" \
    --no-kv-offload \
    $RPC_FLAG \
    --host 0.0.0.0 \
    --port 8081 \
    $TEMPLATE_FLAG \
    $EXTRA_ARGS
