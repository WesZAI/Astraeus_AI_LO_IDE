# ==========================================
# Copyright (c) 2026 Gabriela Berger AI Oberland
# All Rights Reserved.
# This code is subject to the custom NON-COMMERCIAL 
# & ANTI-CORPORATE LICENSE (Maximum 20 PCs) found in the LICENSE file.
# ==========================================
# workspace_manager.py
import os
import json
from pathlib import Path
from tkinter import filedialog
import subprocess

class WorkspaceManager:
    def __init__(self, root):
        self.root = root
        self.current_path = os.path.expanduser("~")
        self.open_files = {}  # {tab_id: {'path': str, 'content': str}}
        self.current_tab = None

    def browse_folders(self):
        folder = filedialog.askdirectory(initialdir=self.current_path)
        if folder:
            self.current_path = folder
            return self._get_directory_tree(folder)
        return None

    def _get_directory_tree(self, path):
        tree = []
        for item in os.listdir(path):
            full_path = os.path.join(path, item)
            is_dir = os.path.isdir(full_path)
            tree.append({
                'name': item,
                'path': full_path,
                'type': 'directory' if is_dir else 'file',
                'children': self._get_directory_tree(full_path) if is_dir else []
            })
        return tree

    def open_file(self, file_path):
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            tab_id = str(len(self.open_files) + 1)
            self.open_files[tab_id] = {
                'path': file_path,
                'content': content,
                'name': os.path.basename(file_path)
            }
            self.current_tab = tab_id
            return content
        except Exception as e:
            return f"Error opening file: {str(e)}"

    def save_file(self, tab_id=None):
        if tab_id is None:
            tab_id = self.current_tab
        if tab_id in self.open_files:
            file_data = self.open_files[tab_id]
            try:
                with open(file_data['path'], 'w') as f:
                    f.write(file_data['content'])
                return True
            except Exception as e:
                return f"Error saving file: {str(e)}"
        return "No file selected"

    def create_file(self, file_type='text', content=''):
        file_path = filedialog.asksaveasfilename(
            defaultextension='.txt' if file_type == 'text' else '.py',
            filetypes=[('Text Files', '*.txt'), ('Python Files', '*.py')]
        )
        if file_path:
            with open(file_path, 'w') as f:
                f.write(content)
            return self.open_file(file_path)
        return None

    def execute_command(self, command):
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=self.current_path,
                capture_output=True,
                text=True
            )
            return {
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode
            }
        except Exception as e:
            return {'error': str(e)}
