# Worker Node Setup (For a Single PC)

This folder contains the setup files required to turn any standard Windows or Linux PC into a **Worker Node** for the local AI cluster.

## 🧠 How it Works

In a traditional setup, an AI model runs entirely on one computer. However, massive models (like 70B or 120B parameter models) require far more GPU memory (VRAM) than a single consumer PC possesses.

This software uses an **RPC (Remote Procedure Call) Cluster Architecture** to solve this:
1. **The Master Node:** The main PC running the IDE. It holds the actual model file (`.gguf`), processes your chat prompts, and orchestrates the cluster.
2. **The Worker Nodes (This PC):** These are "dumb appliances." They do not need Python, they do not need the IDE, and they do not even need the `.gguf` model file. 

**What happens under the hood:**
When you start the `rpc-server` on this PC, it simply opens a network port and waits. When the Master Node loads a massive model, it mathematically splits the model layers into pieces. It looks at the VRAM available on the Worker, sends a portion of the model's layers over the local network to this PC's GPU, and says, *"Hold this in your memory."*

During generation, when the AI is "thinking," the Master sends mathematical matrix multiplication tasks to the Worker. The Worker's GPU calculates the math on its specific layers and sends the raw numbers back to the Master. 

This means **your private data, chat logs, and source code are NEVER stored on the Worker PC.** The Worker only sees raw, unreadable mathematical tensors.

---

## 🛠️ Requirements for this PC

Because this PC is just a mathematical calculator for the Master, the setup is incredibly lightweight:

1. **llama.cpp (RPC Server)**: 
   - **Windows:** Download the pre-compiled `llama-bin-win-cuda-...-x64.zip` release from the official [llama.cpp GitHub](https://github.com/ggerganov/llama.cpp/releases). Extract it anywhere.
   - **Linux:** Clone the `llama.cpp` repository and compile it with `GGML_RPC=ON` enabled via CMake.
   - *Note: The `llama.cpp` version on the Worker MUST exactly match the version on the Master Node.*

2. **Network Access**: Port `50055` (or whichever port you choose to assign this PC) must be open in the local firewall (e.g., Windows Defender).

---

## 🚀 How to Run

You only need to run one script to bring this PC online.

### For Windows:
1. Open `start_worker.ps1` in a text editor (like Notepad).
2. Edit the `$LlamaPath` to point to the folder where you extracted `rpc-server.exe`.
3. Right-click `start_worker.ps1` and select **Run with PowerShell**.

### For Linux:
1. Open `start_worker.sh` in a text editor.
2. Edit the `LLAMA_DIR` to point to the `build/bin` folder where you compiled `llama-server`.
3. Open a terminal and run:
   ```bash
   chmod +x start_worker.sh
   ./start_worker.sh
   ```

Once the script is running, the terminal will say "listening on 0.0.0.0:50055". 

That's it! You can now walk away. When the Master Node starts up, it will automatically detect this PC over the network, load the layers onto its GPU, and begin using its compute power.