# ==========================================
# Copyright (c) 2026 Gabriela Berger AI Oberland
# All Rights Reserved.
# This code is subject to the custom NON-COMMERCIAL 
# & ANTI-CORPORATE LICENSE (Maximum 20 PCs) found in the LICENSE file.
# ==========================================
# agent_interface.py
import json
from network_manager import NetworkManager
from workspace_manager import WorkspaceManager

class AstraeusAgent:
    def __init__(self, workspace_manager):
        self.workspace = workspace_manager
        self.network = NetworkManager()
        self.system_prompt = """
        You are Astraeus, a helpful coding assistant.
        You have access to the user's workspace and can:
        - Read and modify files
        - Execute terminal commands
        - Provide code completions
        - Answer questions about the codebase
        Always maintain context of the current workspace.
        """
        self.manifest = {
            "name": "Astraeus",
            "version": "1.0",
            "capabilities": ["file_operations", "terminal", "code_completion"]
        }

    def process_message(self, user_message, history=[]):
        # Build context
        context = {
            "current_file": self.workspace.open_files.get(self.workspace.current_tab, {}),
            "workspace_tree": self.workspace._get_directory_tree(self.workspace.current_path),
            "history": history
        }

        # Format prompt with context
        prompt = f"{self.system_prompt}\n\nContext: {json.dumps(context, indent=2)}\n\nUser: {user_message}\nAstraeus:"

        # Get model response
        response = self.network.send_to_model(prompt)

        # Process response (could include file operations, etc.)
        return self._process_response(response)

    def _process_response(self, response):
        # Check if response contains commands
        if "file_operation" in response:
            return self._handle_file_operation(response["file_operation"])
        return response.get("text", "I processed your request")

    def _handle_file_operation(self, operation):
        if operation["type"] == "edit":
            tab_id = operation.get("tab_id", self.workspace.current_tab)
            if tab_id in self.workspace.open_files:
                self.workspace.open_files[tab_id]["content"] = operation["content"]
                return f"Edited file: {self.workspace.open_files[tab_id]['name']}"
        elif operation["type"] == "create":
            return self.workspace.create_file(operation.get("type", "text"), operation.get("content", ""))
        elif operation["type"] == "execute":
            return self.workspace.execute_command(operation["command"])
        return "Operation not supported"
