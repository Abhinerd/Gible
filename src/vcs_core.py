import os
import shutil
import json
import time

class VCSEngine:
    """Handles all backend logic for the version control system."""
    def __init__(self, repo_path):
        if not repo_path:
            raise ValueError("Repository path cannot be None.")
        self.repo_path = repo_path
        self.gible_path = os.path.join(self.repo_path, ".gible")
        self.history_path = os.path.join(self.gible_path, "history")
        self.commits_path = os.path.join(self.gible_path, "commits")
        os.makedirs(self.history_path, exist_ok=True)
        os.makedirs(self.commits_path, exist_ok=True)

    def _get_file_history_path(self, file_path):
        """Generates the path to the history directory for a given file."""
        relative_path = os.path.relpath(file_path, self.repo_path)
        return os.path.join(self.history_path, relative_path)

    def get_content_from_snapshot(self, snapshot_path):
        """Reads and returns the content of a snapshot file."""
        try:
            with open(snapshot_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            print(f"Error reading snapshot {snapshot_path}: {e}")
            return f"Error reading snapshot: {e}"

    def create_initial_snapshot(self, file_path):
        """Creates the first version snapshot for a newly added file."""
        try:
            file_history_path = self._get_file_history_path(file_path)
            os.makedirs(file_history_path, exist_ok=True)
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            snapshot_path = os.path.join(file_history_path, f"{int(time.time())}.snapshot")
            with open(snapshot_path, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            print(f"Error creating initial snapshot for {file_path}: {e}")

    def save_snapshot(self, file_path, new_content, current_undo_stack):
        """Saves a new snapshot if content has changed."""
        previous_content = ""
        if current_undo_stack:
            previous_content = self.get_content_from_snapshot(current_undo_stack[-1])

        if new_content == previous_content:
            return None # No changes to save

        file_history_path = self._get_file_history_path(file_path)
        os.makedirs(file_history_path, exist_ok=True)
        timestamp = int(time.time())
        snapshot_path = os.path.join(file_history_path, f"{timestamp}.snapshot")
        with open(snapshot_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return snapshot_path

    def create_commit(self, message):
        """Creates a commit manifest of the current state of all files."""
        manifest = {}
        for root, dirs, files in os.walk(self.repo_path):
            if ".gible" in dirs:
                dirs.remove(".gible")
            for file_name in files:
                if file_name.startswith('.'):
                    continue
                file_path = os.path.join(root, file_name)
                file_history_path = self._get_file_history_path(file_path)
                if os.path.exists(file_history_path) and os.listdir(file_history_path):
                    latest_snapshot = sorted(os.listdir(file_history_path))[-1]
                    relative_path = os.path.relpath(file_path, self.repo_path)
                    manifest[relative_path] = latest_snapshot
        
        if not manifest:
            return False # No changes to commit

        timestamp = int(time.time())
        commit_data = {"timestamp": timestamp, "message": message, "manifest": manifest}
        commit_file_path = os.path.join(self.commits_path, f"{timestamp}.json")

        with open(commit_file_path, 'w') as f:
            json.dump(commit_data, f, indent=4)
        return True

    def get_commit_history(self):
        """Returns a list of all commits, sorted newest first."""
        if not os.path.exists(self.commits_path):
            return []
        
        commit_files = sorted(os.listdir(self.commits_path), reverse=True)
        history = []
        for commit_file in commit_files:
            try:
                with open(os.path.join(self.commits_path, commit_file), 'r') as f:
                    history.append(json.load(f))
            except json.JSONDecodeError:
                print(f"Warning: Could not read commit file {commit_file}")
        return history

    def rollback_to_commit(self, timestamp):
        """Reverts the repository to the state of a specific commit."""
        commit_file_path = os.path.join(self.commits_path, f"{timestamp}.json")
        with open(commit_file_path, 'r') as f:
            commit_data = json.load(f)
        target_manifest = commit_data["manifest"]

        current_files = set()
        for root, dirs, files in os.walk(self.repo_path):
            if ".gible" in dirs:
                dirs.remove(".gible")
            for file_name in files:
                current_files.add(os.path.relpath(os.path.join(root, file_name), self.repo_path))

        files_to_delete = current_files - set(target_manifest.keys())
        for rel_path in files_to_delete:
            os.remove(os.path.join(self.repo_path, rel_path))

        for rel_path, snapshot_name in target_manifest.items():
            dest_path = os.path.join(self.repo_path, rel_path)
            file_history_path = self._get_file_history_path(dest_path)
            snapshot_path = os.path.join(file_history_path, snapshot_name)
            content = self.get_content_from_snapshot(snapshot_path)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with open(dest_path, 'w', encoding='utf-8') as f:
                f.write(content)
        
        for root, dirs, files in os.walk(self.repo_path, topdown=False):
            if ".gible" in dirs:
                dirs.remove(".gible")
            if not os.listdir(root) and root != self.repo_path:
                try:
                    os.rmdir(root)
                except OSError:
                    pass # Ignore if directory is not empty for some reason