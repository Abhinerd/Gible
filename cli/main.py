#!/usr/bin/env python3
"""
Gible Phase-3: Branching + safe merge

Features:
- Text files: line-based diffs (SequenceMatcher)
- Binary files: store full snapshot or binary diff if smaller
- Commit objects reference per-file ("base" or "diff") object OIDs
- Checkout reconstructs files applying chain back to base/diffs
- Branch creation, switching, merge with safe JSON conflict files
"""
from __future__ import annotations
import os
import sys
import json
import zlib
import hashlib
import shutil
from datetime import datetime
from pathlib import Path
from difflib import SequenceMatcher
from typing import List, Tuple, Dict, Optional
import bsdiff4
import uuid
import base64

# -------------------------
# Configuration / Paths
# -------------------------
GIBLE_REPO_DIR = ".gible"
OBJECTS_DIR = "objects"
INDEX_FILE = "index.json"
METADATA_FILE = "metadata.json"
CONFIG_FILE = "config.json"

# -------------------------
# Low-level utilities
# -------------------------
def calculate_hash(data: bytes, algo: str = "sha256") -> str:
    return hashlib.sha256(data).hexdigest() if algo != "sha1" else hashlib.sha1(data).hexdigest()

def compress_data(data: bytes) -> bytes:
    return zlib.compress(data, level=9)

def decompress_data(data: bytes) -> bytes:
    return zlib.decompress(data)

def is_text_content(data: bytes) -> bool:
    try:
        data.decode("utf-8")
        return True
    except Exception:
        return False

# -------------------------
# Object storage
# -------------------------
def objects_dir(repo_path: str) -> str:
    return os.path.join(repo_path, OBJECTS_DIR)

def save_object(repo_path: str, data: bytes, obj_type: str) -> str:
    oid = calculate_hash(data)
    obj_path = os.path.join(objects_dir(repo_path), f"{oid}.{obj_type}")
    os.makedirs(os.path.dirname(obj_path), exist_ok=True)
    with open(obj_path, "wb") as f:
        f.write(compress_data(data))
    return oid

def load_object(repo_path: str, oid: str, obj_type: str) -> bytes:
    obj_path = os.path.join(objects_dir(repo_path), f"{oid}.{obj_type}")
    if not os.path.exists(obj_path):
        raise FileNotFoundError(f"Object {oid}.{obj_type} not found")
    with open(obj_path, "rb") as f:
        return decompress_data(f.read())

# -------------------------
# Text diff generation/application
# -------------------------
def generate_text_diff(old_bytes: bytes, new_bytes: bytes) -> bytes:
    old_lines = old_bytes.decode('utf-8').splitlines(keepends=True)
    new_lines = new_bytes.decode('utf-8').splitlines(keepends=True)
    matcher = SequenceMatcher(None, old_lines, new_lines)
    opcodes = matcher.get_opcodes()
    patch = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag in ("replace", "insert"):
            patch.append([tag, i1, i2, j1, j2, new_lines[j1:j2]])
        else:
            patch.append([tag, i1, i2, j1, j2, None])
    return json.dumps(patch, ensure_ascii=False).encode('utf-8')

def apply_text_diff(base_bytes: bytes, diff_bytes: bytes) -> bytes:
    base_lines = base_bytes.decode('utf-8').splitlines(keepends=True)
    patch = json.loads(diff_bytes.decode('utf-8'))
    result_lines: List[str] = []
    for entry in patch:
        tag, i1, i2, j1, j2, new_chunk = entry
        if tag == "equal":
            result_lines.extend(base_lines[i1:i2])
        elif tag == "replace":
            result_lines.extend(new_chunk)
        elif tag == "delete":
            continue
        elif tag == "insert":
            result_lines.extend(new_chunk)
        else:
            raise ValueError(f"Unknown opcode tag: {tag}")
    return "".join(result_lines).encode('utf-8')

# -------------------------
# Binary diff support
# -------------------------
def generate_binary_diff(old_bytes: bytes, new_bytes: bytes) -> bytes:
    return bsdiff4.diff(old_bytes, new_bytes)

def apply_binary_diff(base_bytes: bytes, diff_bytes: bytes) -> bytes:
    return bsdiff4.patch(base_bytes, diff_bytes)

# -------------------------
# Index (staging) management
# -------------------------
class GibleIndex:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path
        self.index_filepath = os.path.join(repo_path, INDEX_FILE)
        self._data: Dict[str, Dict[str, str]] = {}
        self._load()

    def _load(self):
        if os.path.exists(self.index_filepath):
            try:
                with open(self.index_filepath, "r", encoding='utf-8') as f:
                    self._data = json.load(f)
            except Exception:
                self._data = {}

    def _save(self):
        os.makedirs(os.path.dirname(self.index_filepath), exist_ok=True)
        with open(self.index_filepath, "w", encoding='utf-8') as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def add_file(self, filepath: str, file_hash: str, mode: str):
        self._data[filepath] = {"hash": file_hash, "mode": mode}
        self._save()

    def remove_file(self, filepath: str):
        if filepath in self._data:
            del self._data[filepath]
            self._save()

    def get_all(self) -> Dict[str, Dict[str, str]]:
        return dict(self._data)

    def clear(self):
        self._data = {}
        self._save()

# -------------------------
# Repository core
# -------------------------
class GibleRepository:
    def __init__(self, path: str):
        self.working_dir = os.path.abspath(path)
        self.repo_path = os.path.join(self.working_dir, GIBLE_REPO_DIR)
        self.objects_path = os.path.join(self.repo_path, OBJECTS_DIR)
        self.index = GibleIndex(self.repo_path)
        self.metadata_filepath = os.path.join(self.repo_path, METADATA_FILE)
        self.config_filepath = os.path.join(self.repo_path, CONFIG_FILE)

    # -------------------------
    # Initialization
    # -------------------------
    def init(self):
        if os.path.exists(self.repo_path):
            print(f"Repository already initialized at {self.repo_path}")
            return False
        os.makedirs(self.objects_path, exist_ok=True)
        initial_config = {
            "version": "0.3.0-branchmerge-safe",
            "created_at": datetime.now().isoformat(),
            "author": os.getenv("USER") or os.getenv("USERNAME") or "unknown"
        }
        with open(self.config_filepath, "w", encoding='utf-8') as f:
            json.dump(initial_config, f, indent=2, ensure_ascii=False)
        initial_metadata = {
            "head": None,
            "current_branch": "master",
            "branches": {"master": None},
            "commits": {}
        }
        with open(self.metadata_filepath, "w", encoding='utf-8') as f:
            json.dump(initial_metadata, f, indent=2, ensure_ascii=False)
        self.index.clear()
        print(f"Initialized Gible Phase-3 repository at {self.repo_path}")
        return True

    def is_repo(self) -> bool:
        return os.path.isdir(self.repo_path) and os.path.isdir(self.objects_path) and os.path.isfile(self.config_filepath)

    def load_metadata(self) -> dict:
        if not os.path.exists(self.metadata_filepath):
            raise Exception("Not a Gible repository (metadata missing).")
        with open(self.metadata_filepath, "r", encoding='utf-8') as f:
            return json.load(f)

    def save_metadata(self, metadata: dict):
        with open(self.metadata_filepath, "w", encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

    def load_config(self) -> dict:
        if not os.path.exists(self.config_filepath):
            raise Exception("Not a Gible repository (config missing).")
        with open(self.config_filepath, "r", encoding='utf-8') as f:
            return json.load(f)

    # -------------------------
    # Commit storage
    # -------------------------
    def _write_commit_object(self, commit_obj: dict) -> str:
        commit_bytes = json.dumps(commit_obj, indent=2, ensure_ascii=False).encode('utf-8')
        oid = save_object(self.repo_path, commit_bytes, "commit")
        metadata = self.load_metadata()
        metadata["commits"][oid] = {
            "message": commit_obj.get("message", ""),
            "timestamp": commit_obj.get("timestamp"),
            "author": commit_obj.get("author"),
            "parent": commit_obj.get("parent"),
            "files": commit_obj.get("files", {})
        }
        current_branch = metadata.get("current_branch", "master")
        metadata["branches"][current_branch] = oid
        metadata["head"] = oid
        self.save_metadata(metadata)
        return oid

    def _get_full_commit(self, oid: str) -> dict:
        try:
            commit_bytes = load_object(self.repo_path, oid, "commit")
            return json.loads(commit_bytes.decode('utf-8'))
        except FileNotFoundError:
            metadata = self.load_metadata()
            meta_entry = metadata["commits"].get(oid)
            if not meta_entry:
                raise FileNotFoundError(f"Commit object {oid} not found")
            return {
                "hash": oid,
                "parent": meta_entry.get("parent"),
                "message": meta_entry.get("message"),
                "author": meta_entry.get("author"),
                "timestamp": meta_entry.get("timestamp"),
                "files": meta_entry.get("files", {})
            }

    # -------------------------
    # File reconstruction
    # -------------------------
    def reconstruct_file_bytes(self, commit_oid: str, filepath: str) -> bytes:
        chain: List[Tuple[str, str]] = []
        current_oid = commit_oid
        while current_oid:
            commit_obj = self._get_full_commit(current_oid)
            files_map = commit_obj.get("files", {})
            if filepath in files_map:
                entry = files_map[filepath]
                chain.append((entry[0], entry[1]))
            parent = commit_obj.get("parent")
            if isinstance(parent, list):
                parent = parent[0]  # for merge commits, pick first parent
            current_oid = parent
        if not chain:
            raise FileNotFoundError(f"File '{filepath}' not present in commit {commit_oid}")
        chain.reverse()
        base_type, base_oid = chain[0]
        result = load_object(self.repo_path, base_oid, "base") if base_type == "base" else load_object(self.repo_path, base_oid, base_type)
        for obj_type, oid in chain[1:]:
            if obj_type == "base":
                result = load_object(self.repo_path, oid, "base")
            elif obj_type == "diff":
                diff_bytes = load_object(self.repo_path, oid, "diff")
                result = apply_text_diff(result, diff_bytes) if is_text_content(result) else apply_binary_diff(result, diff_bytes)
            else:
                raise ValueError(f"Unsupported object type in chain: {obj_type}")
        return result

    # -------------------------
    # Staging / add
    # -------------------------
    def add(self, filepath: str):
        abs_path = os.path.join(self.working_dir, filepath)
        if not os.path.exists(abs_path):
            print(f"Error: Path not found: {filepath}")
            return
        paths_to_process = []
        if os.path.isfile(abs_path):
            paths_to_process.append(abs_path)
        else:
            for root, dirs, files in os.walk(abs_path, topdown=True):
                dirs[:] = [d for d in dirs if d != GIBLE_REPO_DIR]
                for name in files:
                    paths_to_process.append(os.path.join(root, name))
        for full_path in paths_to_process:
            rel = os.path.relpath(full_path, self.working_dir)
            try:
                data = Path(full_path).read_bytes()
            except Exception:
                continue
            mode = "text" if is_text_content(data) else "binary"
            content_hash = calculate_hash(data)
            self.index.add_file(rel, content_hash, mode)
            print(f"Staged: {rel} (mode: {mode})")

    # -------------------------
    # Commit
    # -------------------------
    def commit(self, message: str):
        metadata = self.load_metadata()
        head = metadata.get("head")
        current_branch = metadata.get("current_branch", "master")
        staged = self.index.get_all()
        if not staged:
            print("No changes staged. Nothing to commit.")
            return
        new_files_map: Dict[str, List[str]] = {}
        for filepath, info in staged.items():
            abs_path = os.path.join(self.working_dir, filepath)
            if not os.path.exists(abs_path):
                continue
            current_bytes = Path(abs_path).read_bytes()
            is_text = (info.get("mode") == "text")
            prev_entry = None
            if head:
                try:
                    full_commit = self._get_full_commit(head)
                    prev_entry = full_commit.get("files", {}).get(filepath)
                except FileNotFoundError:
                    prev_entry = None
            if prev_entry is None:
                oid = save_object(self.repo_path, current_bytes, "base")
                new_files_map[filepath] = ["base", oid]
                print(f"  {filepath}: stored base ({oid[:8]})")
            else:
                last_bytes = self.reconstruct_file_bytes(head, filepath)
                if is_text:
                    diff_bytes = generate_text_diff(last_bytes, current_bytes)
                    if not json.loads(diff_bytes.decode('utf-8')):
                        new_files_map[filepath] = prev_entry
                        print(f"  {filepath}: no changes (skipped)")
                    else:
                        oid = save_object(self.repo_path, diff_bytes, "diff")
                        new_files_map[filepath] = ["diff", oid]
                        print(f"  {filepath}: stored text diff ({oid[:8]})")
                else:
                    bin_diff = generate_binary_diff(last_bytes, current_bytes)
                    if len(bin_diff) < len(current_bytes):
                        oid = save_object(self.repo_path, bin_diff, "diff")
                        new_files_map[filepath] = ["diff", oid]
                        print(f"  {filepath}: stored binary diff ({oid[:8]})")
                    else:
                        oid = save_object(self.repo_path, current_bytes, "base")
                        new_files_map[filepath] = ["base", oid]
                        print(f"  {filepath}: stored binary base ({oid[:8]})")
        commit_obj = {
            "parent": head,
            "files": new_files_map,
            "message": message,
            "author": self.load_config().get("author", "unknown"),
            "timestamp": datetime.now().isoformat()
        }
        commit_oid = self._write_commit_object(commit_obj)
        print(f"[{current_branch}] {message}")
        print(f"  commit {commit_oid}")
        self.index.clear()
        print("Staging area cleared.")

    # -------------------------
    # Branching / merging
    # -------------------------
    def create_branch(self, name: str):
        metadata = self.load_metadata()
        if name in metadata['branches']:
            print(f"Branch '{name}' already exists")
            return
        metadata['branches'][name] = metadata['head']
        self.save_metadata(metadata)
        print(f"Branch '{name}' created at {metadata['head'][:8]}")

    def switch_branch(self, name: str):
        metadata = self.load_metadata()
        if name not in metadata['branches']:
            print(f"Branch '{name}' does not exist")
            return
        metadata['current_branch'] = name
        head_commit = metadata['branches'][name]
        if head_commit:
            self.checkout(head_commit)
        self.save_metadata(metadata)
        print(f"Switched to branch '{name}'")

    def merge_branch(self, other_branch: str):
        metadata = self.load_metadata()
        if other_branch not in metadata['branches']:
            print(f"Branch '{other_branch}' does not exist")
            return
        current_branch = metadata.get("current_branch", "master")
        current_head = metadata['branches'].get(current_branch)
        other_head = metadata['branches'][other_branch]
        print(f"Merging branch '{other_branch}' into '{current_branch}'")

        merged_files: Dict[str, List[str]] = {}
        files_current = self.get_commit_tree(current_head) if current_head else {}
        files_other = self.get_commit_tree(other_head) if other_head else {}
        all_files = set(files_current.keys()) | set(files_other.keys())

        merge_oid = str(uuid.uuid4())
        merge_dir = os.path.join(self.repo_path, "merge", merge_oid)
        os.makedirs(merge_dir, exist_ok=True)
        conflict_occurred = False

        for f in all_files:
            entry_curr = files_current.get(f)
            entry_other = files_other.get(f)

            if entry_curr is None:
                merged_files[f] = entry_other
            elif entry_other is None:
                merged_files[f] = entry_curr
            else:
                type_curr, oid_curr = entry_curr
                type_other, oid_other = entry_other
                data_curr = self.reconstruct_file_bytes(current_head, f)
                data_other = self.reconstruct_file_bytes(other_head, f)
                
                if is_text_content(data_curr) and is_text_content(data_other):
                    if data_curr != data_other:
                        conflict_occurred = True
                        conflict_file = os.path.join(merge_dir, f.replace(os.sep, "_") + ".json")
                        os.makedirs(os.path.dirname(conflict_file), exist_ok=True)
                        conflict_json = {
                            "file": f,
                            "status": "conflict",
                            "base": "",
                            "ours": data_curr.decode("utf-8"),
                            "theirs": data_other.decode("utf-8")
                        }
                        with open(conflict_file, "w", encoding="utf-8") as mf:
                            json.dump(conflict_json, mf, indent=2, ensure_ascii=False)
                        merged_files[f] = entry_curr
                    else:
                        merged_files[f] = entry_curr
                else:
                    if data_curr != data_other:
                        conflict_occurred = True
                        conflict_file = os.path.join(merge_dir, f.replace(os.sep, "_") + ".json")
                        os.makedirs(os.path.dirname(conflict_file), exist_ok=True)
                        conflict_json = {
                            "file": f,
                            "status": "conflict",
                            "base": "",
                            "ours": base64.b64encode(data_curr).decode("utf-8"),
                            "theirs": base64.b64encode(data_other).decode("utf-8")
                        }
                        with open(conflict_file, "w", encoding="utf-8") as mf:
                            json.dump(conflict_json, mf, indent=2, ensure_ascii=False)
                    merged_files[f] = entry_curr

        merge_commit_obj = {
            "parent": [current_head, other_head],
            "files": merged_files,
            "message": f"Merge branch {other_branch} into {current_branch}",
            "author": self.load_config().get("author", "unknown"),
            "timestamp": datetime.now().isoformat()
        }
        commit_oid = self._write_commit_object(merge_commit_obj)

        if conflict_occurred:
            print(f"Merge commit created: {commit_oid}")
            print(f"Conflicts detected! See .gible/merge/{merge_oid}/ for JSON conflict files.")
        else:
            print(f"Merge commit created: {commit_oid} (no conflicts)")

    def get_commit_tree(self, commit_oid: Optional[str]) -> dict:
        if not commit_oid:
            return {}
        commit_obj = self._get_full_commit(commit_oid)
        return commit_obj.get("files", {})

    # -------------------------
    # Checkout
    # -------------------------
    def checkout(self, commit_oid: str):
        files_map = self.get_commit_tree(commit_oid)
        for filepath, entry in files_map.items():
            obj_type, oid = entry
            if obj_type == "base":
                data = load_object(self.repo_path, oid, "base")
            else:
                data = self.reconstruct_file_bytes(commit_oid, filepath)
            abs_path = os.path.join(self.working_dir, filepath)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            Path(abs_path).write_bytes(data)
        print(f"Checked out commit {commit_oid[:8]}")

    # -------------------------
    # Status
    # -------------------------
    def status(self):
        staged = self.index.get_all()
        if not staged:
            print("No files staged")
        else:
            print("Staged files:")
            for f, info in staged.items():
                print(f"  {f} ({info.get('mode')})")

# -------------------------
# CLI
# -------------------------
def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py <command> [args...]")
        sys.exit(1)

    cmd = sys.argv[1]
    repo = GibleRepository(os.getcwd())

    if cmd == "init":
        repo.init()
    elif cmd == "add":
        if len(sys.argv) < 3:
            print("Usage: add <path>")
        else:
            repo.add(sys.argv[2])
    elif cmd == "commit":
        if len(sys.argv) < 3:
            print("Usage: commit <message>")
        else:
            repo.commit(sys.argv[2])
    elif cmd == "branch":
        if len(sys.argv) < 3:
            print("Usage: branch <name>")
        else:
            repo.create_branch(sys.argv[2])
    elif cmd == "switch":
        if len(sys.argv) < 3:
            print("Usage: switch <branch>")
        else:
            repo.switch_branch(sys.argv[2])
    elif cmd == "merge":
        if len(sys.argv) < 3:
            print("Usage: merge <branch>")
        else:
            repo.merge_branch(sys.argv[2])
    elif cmd == "status":
        repo.status()
    else:
        print(f"Unknown command: {cmd}")

if __name__ == "__main__":
    main()
