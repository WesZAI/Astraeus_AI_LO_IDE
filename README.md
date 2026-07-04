# Local AI IDE & RPC Cluster

Welcome to the **Local AI IDE**, a fully offline-capable, highly autonomous IDE and AI agent built around `llama.cpp` and its RPC server architecture. This project is designed to run massive large language models (like 70B to 120B+ parameter models) efficiently across a local multi-GPU network cluster using consumer hardware.

## 🛑 Important Philosophy: Not Open-Source, but an "Open-Source Enforcer"
**This software itself is NOT Open-Source.** It is distributed under a highly restrictive, anti-corporate custom license. 
However, it is strictly designed to **allow only open-source usage**. Unlike traditional software, this IDE explicitly forbids connecting to closed-source, paid, or proprietary corporate APIs (like OpenAI's GPT-5, Anthropic's Claude, or Google's Gemini). It forces the user to rely exclusively on community-driven open-source models (Llama, Mistral, Gemma) and open-source backend tools (like `llama.cpp`). It is a fortress built to protect and enforce the open-source AI ecosystem, while legally keeping big tech out of its own source code.

## 🏢 Why use this? (For Small Businesses & Privacy)
This setup is explicitly designed for small companies (strictly defined as a maximum of 20 PCs) and individuals who do not want to expose their private data, source code, or intellectual property to the cloud. If you are using Claude or anticipating GPT-5, forget about the endless loops and millions of tokens you send to OpenAI or Anthropic that get copied and stored on their servers. Keep your data secure, private, and entirely on your own PCs.

Instead of renting an expensive 96GB VRAM cloud server that costs thousands of euros per month, you can simply bind your existing office PCs together—the more, the better. By pooling consumer GPUs over the network, you can run a state-of-the-art 128B model (like Mistral-Medium 3.5) entirely offline. 

**Need more speed?** Just replace your standard 1GB network cards and switches with 10GB or even 25GB hardware. You will have your own private AI powerhouse running on your own PCs, and the only thing you pay for is the electricity.

## 🌟 Core Features

- **Multi-GPU RPC Cluster:** Automatically pools VRAM across multiple computers on your local network. The Master node mathematically splits the model layers and offloads them to Worker nodes, allowing you to run models that far exceed the VRAM of a single machine.
- **MCP (Model Context Protocol) Server:** A powerful local server that gives the AI autonomous abilities. It includes tools for:
  - Reading, creating, and surgically replacing code in files.
  - Executing bash commands, managing packages, and killing processes.
  - Web fetching and Google searching for up-to-date documentation.
  - UI control (PyAutoGUI) to manipulate the host's mouse and keyboard.
  
  *Note: The included `mcp_server.py` is a capable but basic local implementation. Because this IDE fully supports the Model Context Protocol, you are entirely free to swap it out for other, potentially more capable MCP servers you find on Hugging Face or GitHub! However, per the license, any MCP server you connect to this cluster MUST also be Open-Source.*
- **Agentic Workflow:** The AI can autonomously act on natural language requests (e.g., "Find my CV, tailor it for this job, and export it to PDF").
- **Voice & Schedule Integration:** Built-in offline Speech-to-Text (Whisper) and Text-to-Speech (Piper) for voice interaction and automated daily briefings.

---

## 🛠️ Hardware Requirements & Configuration

This repository comes pre-configured with a **5-GPU cluster template** in `start_master.sh`. 

### ⚠️ IMPORTANT: Configuring the Worker Nodes
If you have fewer than 5 GPUs, or your GPUs have different VRAM sizes, **you MUST modify the `WORKERS` array** inside `start_master.sh`. Otherwise, the Master will try to connect to non-existent machines and hang.

Open `start_master.sh` and edit the array to match your network. 
Format: `"IP_ADDRESS:PORT:VRAM_GB"`

**Example (if you only have 2 GPUs):**
```bash
WORKERS=(
    # Add your worker nodes here in the format "IP:PORT:VRAM_GB"
    # "10.0.0.1:50051:24" # Master Node (24GB)
    # "10.0.0.2:50052:16" # Worker 1 (16GB)
)
```

---

## 🚀 Setup Guide

### Phase 1: Set up the Worker Nodes (The "Dumb" Appliances)
The Worker nodes do not load the model files. They simply open a port and wait for the Master to send them mathematical tasks.
1. Download or compile `llama.cpp` on each Worker PC.
2. Run the `rpc-server` on each Worker. 
   *(For Windows workers, you can use a simple `.bat` or PowerShell script).*
   ```bash
   ./rpc-server -H 0.0.0.0 -p 50052
   ```
3. **Firewall:** Ensure the firewall on the Worker PC (e.g., Windows Defender, ESET) allows inbound TCP connections on the chosen port (e.g., 50052).

### Phase 2: Set up the Master Node (The Brain)
1. Install Python dependencies: `pip install -r requirements-linux.txt`
2. Compile `llama.cpp` on the Master PC with RPC support enabled.
3. Edit `config.py` to point to your local `.gguf` model files and update the context sizes.
4. Edit `start_master.sh` to configure your `WORKERS` IPs and VRAM.

### Phase 3: Start the IDE
Run the IDE on the Master PC:
```bash
python3 main_window.py
```
The IDE will automatically call `start_master.sh`, which will ping the network, find the active Worker PCs, and distribute the model layers across the cluster.

---

## ⚙️ Advanced Configuration (Context Offloading)

If you are running massive context windows (e.g., 65k or 131k), the KV Cache will consume a huge amount of VRAM. If your GPUs run out of VRAM, the model will spill into system RAM, slowing down generation speed.

To fix this, the provided `start_master.sh` uses the `--no-kv-offload` flag. This forces the massive context memory to stay in your system's CPU RAM, freeing up 100% of your GPU VRAM strictly for the model layers. 

## 🛡️ Safety & Autonomy
The AI agent is given full system access via the MCP server. However, a strict safety rule is enforced in its system prompt: **The AI MUST ask for explicit user permission before executing any destructive commands** (e.g., deleting files, installing packages, or taking over the mouse/keyboard).

---

## 📧 Contact & Licensing

If you have questions about permission to use this software for organizations with more than 20 PCs, please contact: info@ai-oberland.com