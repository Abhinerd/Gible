#!/usr/bin/env python3
"""
Gible Phase-2: Text-diff storage (Myers/SequenceMatcher-based) + binary full snapshots.

Features:
- Text files: store line-based diffs (SequenceMatcher opcodes + new-line content)
- Binary files: store full base snapshots
- Commit objects reference per-file ("base" or "diff") object OIDs
- Checkout reconstructs text files by applying the chain back to the base
- Minimal: no branching/merge features beyond a simple 'master' pointer in metadata

Drop this file in place of your phase-1 script (or paste relevant changes).
"""
from __future__ import annotations
import os
import sys
import json
import zlib
import hashlib
import shutil
import time
from datetime import datetime
from pathlib import Path
from difflib import SequenceMatcher
from typing import List, Tuple, Dict, Optional

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
    if algo == "sha1":
        return hashlib.sha1(data).hexdigest()
    return hashlib.sha256(data).hexdigest()

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
# Object storage (base/diff/commit)
# -------------------------
def objects_dir(repo_path: str) -> str:
    return os.path.join(repo_path, OBJECTS_DIR)

def save_object(repo_path: str, data: bytes, obj_type: str) -> str:
    """
    Save compressed object bytes to .gible/objects/<oid>.<obj_type>
    Return the object id (hash of raw data).
    Allowed obj_type examples: "base", "diff", "commit"
    """
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
# Diff generation and application (line-based)
# -------------------------
# We'll store a compact, easy-to-apply JSON patch derived from SequenceMatcher opcodes.
# Patch format (JSON-serializable list):
# [ [tag, i1, i2, j1, j2, new_lines_list_or_null], ... ]
# For 'replace' and 'insert' entries, new_lines_list contains strings (with line endings).
# For 'equal' and 'delete' entries, new_lines_list is null.

def generate_text_diff(old_bytes: bytes, new_bytes: bytes) -> bytes:
    old_lines = old_bytes.decode('utf-8').splitlines(keepends=True)
    new_lines = new_bytes.decode('utf-8').splitlines(keepends=True)

    matcher = SequenceMatcher(None, old_lines, new_lines)
    opcodes = matcher.get_opcodes()

    patch = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag in ("replace", "insert"):
            # store the new content chunk (list of lines)
            patch.append([tag, i1, i2, j1, j2, new_lines[j1:j2]])
        else:
            # equal or delete - no new content needed
            patch.append([tag, i1, i2, j1, j2, None])

    json_bytes = json.dumps(patch, ensure_ascii=False).encode('utf-8')
    return json_bytes

def apply_text_diff(base_bytes: bytes, diff_bytes: bytes) -> bytes:
    base_lines = base_bytes.decode('utf-8').splitlines(keepends=True)
    patch = json.loads(diff_bytes.decode('utf-8'))

    result_lines: List[str] = []
    for entry in patch:
        tag, i1, i2, j1, j2, new_chunk = entry
        if tag == "equal":
            # take from base
            result_lines.extend(base_lines[i1:i2])
        elif tag == "replace":
            # take the new_chunk (was saved into the diff)
            if new_chunk is None:
                # should not happen
                raise ValueError("replace opcode missing new chunk")
            result_lines.extend(new_chunk)
        elif tag == "delete":
            # skip base[i1:i2]
            continue
        elif tag == "insert":
            if new_chunk is None:
                raise ValueError("insert opcode missing new chunk")
            result_lines.extend(new_chunk)
        else:
            raise ValueError(f"Unknown opcode tag: {tag}")

    return "".join(result_lines).encode('utf-8')

# -------------------------
# Index (staging) management
# -------------------------
class GibleIndex:
    """
    Staging area: maps file path -> {"hash": content-hash, "mode": "text"|"binary"}
    """
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
# Repository core (Phase-2)
# -------------------------
class GibleRepository:
    def __init__(self, path: str):
        self.working_dir = os.path.abspath(path)
        self.repo_path = os.path.join(self.working_dir, GIBLE_REPO_DIR)
        self.objects_path = os.path.join(self.repo_path, OBJECTS_DIR)
        self.index = GibleIndex(self.repo_path)
        self.metadata_filepath = os.path.join(self.repo_path, METADATA_FILE)
        self.config_filepath = os.path.join(self.repo_path, CONFIG_FILE)

    # Initialization and metadata
    def init(self):
        if os.path.exists(self.repo_path):
            print(f"Repository already initialized at {self.repo_path}")
            return False
        os.makedirs(self.objects_path, exist_ok=True)

        initial_config = {
            "version": "0.2.0-textdiff",
            "created_at": datetime.now().isoformat(),
            "author": os.getenv("USER") or os.getenv("USERNAME") or "unknown"
        }
        with open(self.config_filepath, "w", encoding='utf-8') as f:
            json.dump(initial_config, f, indent=2, ensure_ascii=False)

        initial_metadata = {
            "head": None,
            "branches": {"master": None},
            "commits": {}  # commit_id -> commit object as JSON (small index)
        }
        with open(self.metadata_filepath, "w", encoding='utf-8') as f:
            json.dump(initial_metadata, f, indent=2, ensure_ascii=False)

        self.index.clear()
        print(f"Initialized Gible Phase-2 repository at {self.repo_path}")
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

    # --- Helpers to work with commit objects stored in metadata['commits'] ---
    def _write_commit_object(self, commit_obj: dict) -> str:
        """
        Serialize the commit object and save as a 'commit' object in objects/.
        Also add a small index entry in metadata['commits'] for fast lookup.
        """
        commit_bytes = json.dumps(commit_obj, indent=2, ensure_ascii=False).encode('utf-8')
        oid = save_object(self.repo_path, commit_bytes, "commit")
        commit_obj_with_hash = dict(commit_obj)
        commit_obj_with_hash["hash"] = oid

        # persist into metadata index
        metadata = self.load_metadata()
        metadata["commits"][oid] = {
            "message": commit_obj.get("message", ""),
            "timestamp": commit_obj.get("timestamp"),
            "author": commit_obj.get("author"),
            "parent": commit_obj.get("parent"),
            # we store a compact pointer to files (mapping filepath -> [type, oid])
            "files": commit_obj.get("files", {})
        }
        metadata["head"] = oid
        # update master branch pointer if unchanged or missing
        if "master" not in metadata.get("branches", {}) or metadata["branches"]["master"] == commit_obj.get("parent"):
            metadata["branches"]["master"] = oid

        self.save_metadata(metadata)
        return oid

    def _get_full_commit(self, oid: str) -> dict:
        """
        Return full commit object (read the commit object from objects/commit).
        """
        try:
            commit_bytes = load_object(self.repo_path, oid, "commit")
        except FileNotFoundError:
            # fallback to metadata index record if objects missing (unlikely)
            metadata = self.load_metadata()
            meta_entry = metadata["commits"].get(oid)
            if not meta_entry:
                raise FileNotFoundError(f"Commit object {oid} not found")
            # reconstruct a minimal commit object from metadata index
            return {
                "hash": oid,
                "parent": meta_entry.get("parent"),
                "message": meta_entry.get("message"),
                "author": meta_entry.get("author"),
                "timestamp": meta_entry.get("timestamp"),
                "files": meta_entry.get("files", {})
            }
        return json.loads(commit_bytes.decode('utf-8'))

    # Reconstruct a file's bytes at a given commit oid (walk chain back to base and apply diffs)
    def reconstruct_file_bytes(self, commit_oid: str, filepath: str) -> bytes:
        """
        Walk back from commit_oid through parents, collect entries for filepath.
        Then reconstruct starting from the oldest base.
        """
        # Build chain newest->oldest
        chain: List[Tuple[str, str]] = []  # list of (obj_type, oid)
        current_oid = commit_oid
        while current_oid:
            try:
                commit_obj = self._get_full_commit(current_oid)
            except FileNotFoundError:
                break
            files_map = commit_obj.get("files", {})
            if filepath in files_map:
                entry = files_map[filepath]
                # entry expected as [obj_type, oid]
                chain.append((entry[0], entry[1]))
            current_oid = commit_obj.get("parent")

        if not chain:
            raise FileNotFoundError(f"File '{filepath}' not present in commit {commit_oid}")

        # chain currently newest -> oldest. Reverse to oldest -> newest
        chain.reverse()

        # first item must be base (or we treat it as base)
        base_type, base_oid = chain[0]
        if base_type != "base":
            # If the oldest entry isn't a base (shouldn't happen), try to load it anyway
            base_bytes = load_object(self.repo_path, base_oid, base_type)
        else:
            base_bytes = load_object(self.repo_path, base_oid, "base")

        result = base_bytes
        # apply remaining entries
        for obj_type, oid in chain[1:]:
            if obj_type == "base":
                result = load_object(self.repo_path, oid, "base")
            elif obj_type == "diff":
                diff_bytes = load_object(self.repo_path, oid, "diff")
                result = apply_text_diff(result, diff_bytes)
            else:
                raise ValueError(f"Unsupported object type in chain: {obj_type}")

        return result

    # High-level operations
    def add(self, filepath: str):
        abs_path = os.path.join(self.working_dir, filepath)
        if not os.path.exists(abs_path):
            print(f"Error: File not found: {filepath}")
            return
        data = Path(abs_path).read_bytes()
        mode = "text" if is_text_content(data) else "binary"
        content_hash = calculate_hash(data)
        self.index.add_file(filepath, content_hash, mode)
        print(f"Staged: {filepath} (mode: {mode})")

    def commit(self, message: str):
        metadata = self.load_metadata()
        head = metadata.get("head")
        staged = self.index.get_all()
        if not staged:
            print("No changes staged. Nothing to commit.")
            return

        new_files_map: Dict[str, List[str]] = {}  # filepath -> [obj_type, oid]
        for filepath, info in staged.items():
            abs_path = os.path.join(self.working_dir, filepath)
            if not os.path.exists(abs_path):
                print(f"Warning: staged file missing: {filepath}; treating as deletion (skip).")
                continue
            current_bytes = Path(abs_path).read_bytes()
            is_text = (info.get("mode") == "text")
            # Determine previous entry (if any)
            prev_entry = None
            if head:
                # metadata['commits'][head]['files'][filepath] may exist
                meta_commit_entry = metadata.get("commits", {}).get(head, {})
                prev_files = meta_commit_entry.get("files", {}) if meta_commit_entry else {}
                prev_entry = prev_files.get(filepath)

                # If metadata index does not include full commit content, fallback to reading commit object
                if prev_entry is None:
                    try:
                        full_commit = self._get_full_commit(head)
                        prev_entry = full_commit.get("files", {}).get(filepath)
                    except FileNotFoundError:
                        prev_entry = None

            if prev_entry is None:
                # first commit of this file -> store base
                oid = save_object(self.repo_path, current_bytes, "base")
                new_files_map[filepath] = ["base", oid]
                print(f"  {filepath}: stored base ({oid[:8]})")
            else:
                # reconstruct last bytes to compute diff
                try:
                    last_bytes = self.reconstruct_file_bytes(head, filepath)
                except FileNotFoundError:
                    # fallback: treat as no previous -> base
                    last_bytes = b""

                if is_text:
                    # store diff against last_bytes
                    diff_bytes = generate_text_diff(last_bytes, current_bytes)
                    # if diff is empty (no changes), skip storing entry (no-op)
                    if diff_bytes == b"[]":
                        # no-op; keep previous entry (no change)
                        new_files_map[filepath] = prev_entry
                        print(f"  {filepath}: no changes (skipped)")
                    else:
                        oid = save_object(self.repo_path, diff_bytes, "diff")
                        new_files_map[filepath] = ["diff", oid]
                        print(f"  {filepath}: stored diff ({oid[:8]})")
                else:
                    # binary -> store full base snapshot
                    oid = save_object(self.repo_path, current_bytes, "base")
                    new_files_map[filepath] = ["base", oid]
                    print(f"  {filepath}: stored binary base ({oid[:8]})")

        # Build commit object
        commit_obj = {
            "parent": head,
            "files": new_files_map,
            "message": message,
            "author": self.load_config().get("author", "unknown"),
            "timestamp": datetime.now().isoformat()
        }

        commit_oid = self._write_commit_object(commit_obj)
        print(f"[master] {message}")
        print(f"  commit {commit_oid}")

        # Clear index
        self.index.clear()
        print("Staging area cleared.")

    def get_commit_tree(self, commit_oid: str) -> Dict[str, List[str]]:
        commit = self._get_full_commit(commit_oid)
        return commit.get("files", {})

    def get_file_at_commit(self, commit_oid: str, filepath: str):
        """
        Returns (bytes) of the file content at the given commit.
        For text files this reconstructs by applying diffs; for binary it returns bytes directly.
        """
        files_map = self.get_commit_tree(commit_oid)
        entry = files_map.get(filepath)
        if not entry:
            raise FileNotFoundError(f"File '{filepath}' not found in commit '{commit_oid}'")

        obj_type, oid = entry
        if obj_type == "base":
            return load_object(self.repo_path, oid, "base")
        elif obj_type == "diff":
            # Need to reconstruct chain to apply diffs
            return self.reconstruct_file_bytes(commit_oid, filepath)
        else:
            raise ValueError(f"Unsupported object type '{obj_type}'")

    def checkout(self, commit_oid: str, target_dir: Optional[str] = None):
        if target_dir is None:
            target_dir = self.working_dir
        print(f"Checking out {commit_oid[:8]} to {target_dir}...")
        files_map = self.get_commit_tree(commit_oid)
        for filepath, entry in files_map.items():
            try:
                content_bytes = self.get_file_at_commit(commit_oid, filepath)
            except Exception as e:
                print(f"  Error reconstructing {filepath}: {e}")
                continue
            full_target = os.path.join(target_dir, filepath)
            os.makedirs(os.path.dirname(full_target), exist_ok=True)
            # decide mode: text if utf-8 decodable
            if is_text_content(content_bytes):
                with open(full_target, "w", encoding='utf-8', newline='') as f:
                    f.write(content_bytes.decode('utf-8'))
            else:
                with open(full_target, "wb") as f:
                    f.write(content_bytes)
            print(f"  Restored {filepath}")
        # update HEAD in metadata
        metadata = self.load_metadata()
        metadata["head"] = commit_oid
        self.save_metadata(metadata)
        print(f"HEAD updated to {commit_oid[:8]}")

    def status(self):
        if not self.is_repo():
            print("Not a Gible repository.")
            return
        metadata = self.load_metadata()
        print(f"Gible repo at {self.repo_path}")
        print(f"HEAD: {metadata.get('head')}")
        staged = self.index.get_all()
        if staged:
            print("Staged files:")
            for p, info in staged.items():
                print(f"  - {p} ({info.get('mode')})")
        else:
            print("No files staged.")

    def destroy_repo(self):
        if os.path.exists(self.repo_path):
            shutil.rmtree(self.repo_path)
            print(f"Destroyed repository at {self.repo_path}")
        else:
            print("No repository to destroy.")

# -------------------------
# CLI
# -------------------------
def find_repo(path: str = ".") -> Optional[GibleRepository]:
    current = os.path.abspath(path)
    while True:
        candidate = GibleRepository(current)
        if candidate.is_repo():
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent

def usage():
    print("Usage: python gible.py <command> [args]")
    print("Commands: init, status, destroy, add <file>, commit -m <msg>, checkout <commit_oid>")

def main(argv):
    if len(argv) < 2:
        usage()
        return
    command = argv[1]

    if command == "init":
        GibleRepository(os.getcwd()).init()
        return

    repo = find_repo()
    if not repo:
        print("Error: Not a gible repository. Run 'python gible.py init' first.")
        return

    if command == "status":
        repo.status()
    elif command == "destroy":
        repo.destroy_repo()
    elif command == "add":
        if len(argv) < 3:
            print("Usage: add <file>")
            return
        repo.add(argv[2])
    elif command == "commit":
        if len(argv) < 4 or argv[2] != "-m":
            print('Usage: commit -m "message"')
            return
        repo.commit(argv[3])
    elif command == "checkout":
        if len(argv) < 3:
            print("Usage: checkout <commit_oid>")
            return
        repo.checkout(argv[2])
    else:
        print(f"Unknown command: {command}")
        usage()

if __name__ == "__main__":
    main(sys.argv)
