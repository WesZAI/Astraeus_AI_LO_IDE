#!/bin/bash
# start_worker.sh

LLAMA_DIR="/path/to/your/llama.cpp/build/bin"
PORT=50055

echo "Starte Llama RPC Worker auf Port $PORT..."
cd "$LLAMA_DIR" || { echo "Fehler: Verzeichnis $LLAMA_DIR nicht gefunden."; exit 1; }

if [ -f "./rpc-server" ]; then
    ./rpc-server -H 0.0.0.0 -p $PORT
else
    echo "Fehler: rpc-server nicht gefunden in $LLAMA_DIR."
    exit 1
fi