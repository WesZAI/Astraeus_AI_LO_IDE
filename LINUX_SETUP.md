# Astraeus IDE — Run on the Linux PC

You are at the offline Ubuntu/ROCm machine. The project should live in the current directory (`.`). Follow these four steps in order.


## Step 1 — Activate the venv

The launcher `open_IDE` expects the venv at `../Agents/venv`.

    source ../Agents/venv/bin/activate

If the venv doesn't exist yet (first time on this PC), create it:

    sudo apt install python3.12 python3.12-venv python3-tk     # one-time, needs net
    cd .
    python3.12 -m venv venv
    source venv/bin/activate


## Step 2 — Install the Python deps from the local wheels (offline)

The project ships its own wheels under `wheels-linux/`. No internet needed:

    pip install --no-index \
                --find-links ./wheels-linux \
                -r ./requirements-linux.txt

Quick check that it worked:

    python -c "import requests, jinja2; print('ok')"

If pip says "no matching wheel", your Python is not 3.12.
Run `python3 --version` and re-download wheels for that version on the Windows PC.


## Step 3 — Launch the IDE

From the project folder:

    python main_window.py
    
    
    Error: (venv) user@hostname:~/IDE$ python main_window.py
Traceback (most recent call last):
  File "./main_window.py", line 1202, in <module>
    app = MainWindow(root)
          ^^^^^^^^^^^^^^^^
  File "./main_window.py", line 71, in __init__
    self.memory_bridge = MemoryBridge('memory.sqlite3')
                         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "./memory_bridge.py", line 12, in __init__
    self._initialize_global_patterns()
  File "./memory_bridge.py", line 22, in _initialize_global_patterns
    cursor = self.conn.cursor()
             ^^^^^^^^^^^^^^^^
AttributeError: 'NoneType' object has no attribute 'cursor'





Or use the helper:

    ./open_IDE

A Tk window titled "Astraeus IDE" should open.


## Step 4 — Test the AI agent end-to-end

Inside the GUI:

1. **Pick a model** — top-right dropdown → `Astraeus`.
2. **Start Model** — click the *Start Model* button. Logs stream into the terminal
   pane below; wait for "Server responded to /v1/models".
3. **Agent mode on** — make sure the `Agent` checkbox next to the model dropdown
   is ticked (it's on by default).
4. **Open a workspace folder** — File → Open Folder (or the explorer button) →
   pick the folder you want the AI to work inside. The agent is locked to that folder.
5. **Chat** — in the chat input type something like
   *"list the files here and read main_window.py"* and press *Send*. You should see:
   - your message in the chat pane,
   - one or more lines like `→ tool: list_dir(...)` and `✓ ok` as the agent acts,
   - a final `Astraeus: ...` answer.


## If the model never responds

- Check the terminal pane for llama-server errors.
- Confirm the server is up: `curl http://127.0.0.1:8081/v1/models`
- Run the start command directly in a separate terminal to see raw error output:

      export HIP_VISIBLE_DEVICES=0 && \
        ../llama.cpp/build/bin/llama-server \
          -m ../Agents/Astraeus/models/Astraeus_Dolphin_Venice_Full_Hf-24B-F16.gguf \
          -c 32768 --host 127.0.0.1 --port 8081

- If `llama-server` lives somewhere else now, edit the `LLAMA_SERVER` constant
  at the top of `config.py` (one place — it's used by all three model entries).


## Things to remember

- **Never** pass `-ngl` to llama-server on this ROCm box — it will crash.
  ROCm scales layers automatically.
- Only one llama-server at a time (24 GB VRAM cap). The IDE's *Start Model*
  button kills any previous one before launching a new one.
- The agent has full read / write / run-bash powers, but only inside the
  workspace folder you opened. Anything outside is refused.
- Changing the workspace folder resets the agent's chat history.
- The three configured models all share `127.0.0.1:8081`, so switching
  models means stopping the current one and starting another.
