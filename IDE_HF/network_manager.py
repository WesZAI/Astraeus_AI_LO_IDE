# ==========================================
# Copyright (c) 2026 Gabriela Berger AI Oberland
# All Rights Reserved.
# This code is subject to the custom NON-COMMERCIAL 
# & ANTI-CORPORATE LICENSE (Maximum 20 PCs) found in the LICENSE file.
# ==========================================
import requests
import subprocess
import time
from config import AppConfig
from tkinter import messagebox

class NetworkManager:
    def __init__(self):
        self.config = AppConfig()
        self.active_model = None
        self.active_agent = None

    def start_model_server(self, model_name):
        if model_name not in self.config.models:
            messagebox.showerror("Error", f"Model {model_name} not found")
            return False

        model = self.config.models[model_name]
        try:
            # Start the model server
            self.model_process = subprocess.Popen(
                model.command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            # Wait for server to start
            max_attempts = 30
            for _ in range(max_attempts):
                try:
                    response = requests.get(f"http://{model.host}:{model.port}/v1/models", timeout=1)
                    if response.status_code == 200:
                        self.active_model = model
                        messagebox.showinfo("Success", f"{model_name} server started successfully")
                        return True
                except:
                    time.sleep(1)

            messagebox.showerror("Error", f"Failed to start {model_name} server")
            return False

        except Exception as e:
            messagebox.showerror("Error", f"Failed to start model: {str(e)}")
            return False

    def start_agent(self, agent_name):
        if agent_name not in self.config.agents:
            messagebox.showerror("Error", f"Agent {agent_name} not found")
            return False

        agent = self.config.agents[agent_name]
        try:
            # Start the agent
            self.agent_process = subprocess.Popen(
                agent.command,
                shell=True,
                cwd=agent.workdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            self.active_agent = agent
            messagebox.showinfo("Success", f"{agent_name} agent started successfully")
            return True

        except Exception as e:
            messagebox.showerror("Error", f"Failed to start agent: {str(e)}")
            return False

    def send_to_model(self, prompt):
        if not self.active_model:
            return {"error": "No active model"}

        try:
            response = requests.post(
                f"http://{self.active_model.host}:{self.active_model.port}/v1/completions",
                json={"prompt": prompt, "max_tokens": 800},
                timeout=600
            )
            return response.json()
        except Exception as e:
            return {"error": str(e)}

    def send_to_agent(self, message):
        if not self.active_agent:
            return {"error": "No active agent"}

        # In a real implementation, this would connect to the agent's API
        return {"response": f"Agent {self.active_agent.name} received: {message}"}

    def post(self, url, json=None, data=None, headers=None, timeout=10):
        """Generic POST method for main_window.py compatibility."""
        response = requests.post(url, json=json, data=data, headers=headers, timeout=timeout)
        response.raise_for_status()
        return response

    def get(self, url, params=None, headers=None, timeout=10):
        """Generic GET method for main_window.py compatibility."""
        response = requests.get(url, params=params, headers=headers, timeout=timeout)
        response.raise_for_status()
        return response
