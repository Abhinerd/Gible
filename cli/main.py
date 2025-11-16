#!/usr/bin/env python3
"""
Gible CLI

Features:
- Text files: line-based diffs (SequenceMatcher)
- Binary files: store full snapshot or binary diff if smaller
- Commit objects reference per-file ("base" or "diff") object OIDs
- Checkout reconstructs files applying chain back to base/diffs
- Branch creation, switching, merge with safe JSON conflict files
- File deletion tracking via 'rm' and modified commit logic
- Interactive 3-way merge with conflict markers
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
MERGE_HEAD_FILE = "MERGE_HEAD"
MERGE_CONFLICT_DIR = "merge_conflicts"


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
        else:
            raise KeyError(f"File {filepath} not in index")

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
            "version": "0.4.0-merge-conflict",
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
        print(f"Initialized Gible Phase-4 repository at {self.repo_path}")
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
    # Staging / add / rm
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

    def rm(self, filepath: str):
        abs_path = os.path.join(self.working_dir, filepath)
        
        if os.path.exists(abs_path):
            try:
                os.remove(abs_path)
                print(f"Removed from working directory: {filepath}")
            except Exception as e:
                print(f"Error removing file {filepath}: {e}")
                # Don't return, still try to remove from index
        
        # Now, remove it from the index
        try:
            self.index.remove_file(filepath)
            print(f"Removed from index (staged for deletion): {filepath}")
        except KeyError:
            # This is fine, maybe it was never added
            print(f"File {filepath} not in index or already removed.")

    # -------------------------
    # Commit
    # -------------------------
    def commit(self, message: str, merge_parents: Optional[List[str]] = None):
        metadata = self.load_metadata()
        head = metadata.get("head")
        current_branch = metadata.get("current_branch", "master")

        # --- NEW: Check for MERGE_HEAD ---
        merge_head_path = os.path.join(self.repo_path, MERGE_HEAD_FILE)
        parent_oids = [head] # Default parent
        
        if os.path.exists(merge_head_path):
            if merge_parents:
                # This is the auto-commit from a successful merge
                parent_oids = merge_parents
            else:
                # This is the user finalizing a conflicted merge
                print("Finalizing merge...")
                with open(merge_head_path, "r") as f:
                    other_head = f.read().strip()
                parent_oids = [head, other_head] # Set parent to BOTH
                
            # Clean up the merge state file
            os.remove(merge_head_path)
            
            # Clean up the conflict JSON directory
            merge_dir = os.path.join(self.repo_path, MERGE_CONFLICT_DIR)
            if os.path.exists(merge_dir):
                shutil.rmtree(merge_dir)

        elif merge_parents:
            # This is an auto-commit from a successful merge
             parent_oids = merge_parents
        
        # Get the files from the parent commit
        parent_files: Dict[str, List[str]] = {}
        if parent_oids[0]: # Use the first parent (current branch head) for comparison
            try:
                parent_files = self._get_full_commit(parent_oids[0]).get("files", {})
            except FileNotFoundError:
                print(f"Warning: Head commit {parent_oids[0]} not found. Treating as initial commit.")
                head = None # Reset head if object is missing

        staged_files = self.index.get_all()
        
        if not staged_files and not head:
             print("Nothing to commit (empty repository)")
             return
        
        # This will be the file map for the NEW commit
        new_files_map = {}

        # Combine all possible files from parent and index to process them
        all_known_files = set(parent_files.keys()) | set(staged_files.keys())

        if not all_known_files and not head:
            print("Nothing staged for initial commit.")
            return

        has_changes = False
        for filepath in all_known_files:
            in_parent = filepath in parent_files
            in_staged = filepath in staged_files
            
            staged_info = staged_files.get(filepath)
            parent_entry = parent_files.get(filepath)

            if in_parent and not in_staged:
                # Case 1: DELETION
                # Was in parent, but not in index (because 'gible rm' removed it)
                print(f"  {filepath}: deleted")
                # We do nothing; it's simply not added to new_files_map
                has_changes = True
                
            elif not in_parent and in_staged:
                # Case 2: ADDITION
                # Not in parent, but in index. This is a new file.
                abs_path = os.path.join(self.working_dir, filepath)
                if not os.path.exists(abs_path):
                    continue
                
                current_bytes = Path(abs_path).read_bytes()
                oid = save_object(self.repo_path, current_bytes, "base")
                new_files_map[filepath] = ["base", oid]
                print(f"  {filepath}: stored base ({oid[:8]})")
                has_changes = True
                
            elif in_parent and in_staged:
                # Case 3: MODIFICATION (or no change)
                # Was in parent AND is still in index. Check for changes.
                abs_path = os.path.join(self.working_dir, filepath)
                if not os.path.exists(abs_path):
                    continue
                
                current_bytes = Path(abs_path).read_bytes()
                is_text = (staged_info.get("mode") == "text")
                
                # Reconstruct the last version
                last_bytes = self.reconstruct_file_bytes(head, filepath)

                if last_bytes == current_bytes:
                    # No change, just copy the old entry
                    new_files_map[filepath] = parent_entry
                    print(f"  {filepath}: no changes")
                else:
                    # It changed, store a diff or new base
                    has_changes = True
                    if is_text:
                        diff_bytes = generate_text_diff(last_bytes, current_bytes)
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
        
        if not has_changes:
             print("No changes staged. Nothing to commit.")
             return

        # --- (Rest of your commit logic) ---
        commit_obj = {
            "parent": parent_oids[0] if len(parent_oids) == 1 else parent_oids,
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

    def switch_branch(self, name: str, silent: bool = False):
        metadata = self.load_metadata()
        if name not in metadata['branches']:
            if not silent: print(f"Branch '{name}' does not exist")
            return
            
        merge_head_path = os.path.join(self.repo_path, MERGE_HEAD_FILE)
        if os.path.exists(merge_head_path):
            print("Error: Cannot switch branch. A merge is in progress.")
            print("Please resolve conflicts and run 'gible commit'.")
            return
            
        metadata['current_branch'] = name
        head_commit = metadata['branches'][name]
        if head_commit:
            self.checkout(head_commit)
        else:
            # New branch with no commits, clear working dir
            # (Git would keep files, but for this simple VCS, let's clear)
            # This part is tricky, for now we just checkout 'None'
            self.checkout(head_commit) 
            
        self.save_metadata(metadata)
        if not silent: print(f"Switched to branch '{name}'")
        
    def _find_common_ancestor(self, oid1: Optional[str], oid2: Optional[str]) -> Optional[str]:
        """Finds the first common ancestor between two commits."""
        if not oid1 or not oid2:
            return None
            
        ancestors1 = set()
        q = [oid1]
        while q:
            oid = q.pop(0)
            if oid in ancestors1:
                continue
            ancestors1.add(oid)
            try:
                commit = self._get_full_commit(oid)
                parents = commit.get("parent")
                if parents:
                    if isinstance(parents, list):
                        q.extend(parents)
                    else:
                        q.append(parents)
            except FileNotFoundError:
                continue # Reached end or broken commit

        q = [oid2]
        while q:
            oid = q.pop(0)
            if oid in ancestors1:
                return oid # Found it
            if oid is None:
                continue
            try:
                commit = self._get_full_commit(oid)
                parents = commit.get("parent")
                if parents:
                    if isinstance(parents, list):
                        q.extend(parents)
                    else:
                        q.append(parents)
            except FileNotFoundError:
                continue
        return None # No common ancestor

    def merge_branch(self, other_branch: str):
        metadata = self.load_metadata()
        if other_branch not in metadata['branches']:
            print(f"Branch '{other_branch}' does not exist")
            return
            
        current_branch = metadata.get("current_branch", "master")
        current_head = metadata['branches'].get(current_branch)
        other_head = metadata['branches'][other_branch]

        if current_head == other_head:
            print("Already up-to-date.")
            return
            
        # --- NEW: Check for merge in progress ---
        merge_head_path = os.path.join(self.repo_path, MERGE_HEAD_FILE)
        if os.path.exists(merge_head_path):
            print("Error: A merge is already in progress.")
            print("Please resolve conflicts and run 'gible commit'.")
            return
            
        # --- NEW: Find common ancestor ---
        base_head = self._find_common_ancestor(current_head, other_head)
        
        if base_head == other_head:
            print(f"Branch '{current_branch}' already includes '{other_branch}'.")
            return
        if base_head == current_head:
            print(f"Fast-forwarding '{current_branch}' to '{other_branch}'...")
            self.checkout(other_head)
            metadata['branches'][current_branch] = other_head
            metadata['head'] = other_head
            self.save_metadata(metadata)
            return

        print(f"Merging '{other_branch}' ({other_head[:7]}) into '{current_branch}' ({current_head[:7]})")
        print(f"Common ancestor: {base_head[:7] if base_head else 'None'}")
        
        files_base = self.get_commit_tree(base_head) if base_head else {}
        files_current = self.get_commit_tree(current_head) if current_head else {}
        files_other = self.get_commit_tree(other_head) if other_head else {}
        
        all_files = set(files_base.keys()) | set(files_current.keys()) | set(files_other.keys())
        
        conflict_occurred = False
        merge_dir = os.path.join(self.repo_path, MERGE_CONFLICT_DIR)
        if os.path.exists(merge_dir):
            shutil.rmtree(merge_dir) # Clear old conflict dir
        
        self.index.clear() # Start merge with a clean index

        for f in all_files:
            abs_path = os.path.join(self.working_dir, f)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            
            # Get the three versions of the file
            try:
                base_bytes = self.reconstruct_file_bytes(base_head, f) if f in files_base else None
                ours_bytes = self.reconstruct_file_bytes(current_head, f) if f in files_current else None
                theirs_bytes = self.reconstruct_file_bytes(other_head, f) if f in files_other else None
            except FileNotFoundError:
                print(f"Warning: Could not reconstruct {f}, skipping.")
                continue

            merged_bytes = None
            is_text = True
            
            # Case 1: All three are None (shouldn't happen with all_files set)
            if ours_bytes is None and theirs_bytes is None:
                continue # Not in ours or theirs
            
            # Case 2: File was deleted by us
            if ours_bytes is None:
                if theirs_bytes == base_bytes:
                    # We deleted, they did nothing. Deletion wins.
                    print(f"  {f}: deleted (ours)")
                    if os.path.exists(abs_path): os.remove(abs_path)
                    continue # Not added to index
                else:
                    # We deleted, they modified. CONFLICT.
                    print(f"  {f}: CONFLICT (deleted by us, modified by them)")
                    conflict_occurred = True
                    # (To handle this, we'd write a conflict file)
                continue
                
            # Case 3: File was deleted by them
            if theirs_bytes is None:
                if ours_bytes == base_bytes:
                    # They deleted, we did nothing. Deletion wins.
                    print(f"  {f}: deleted (theirs)")
                    if os.path.exists(abs_path): os.remove(abs_path)
                    continue # Not added to index
                else:
                    # They deleted, we modified. CONFLICT.
                    print(f"  {f}: CONFLICT (modified by us, deleted by them)")
                    conflict_occurred = True
                continue

            # --- All 3 files exist (or base is None) ---
            is_text = is_text_content(ours_bytes) and is_text_content(theirs_bytes)

            # Case 4: No change or same change
            if ours_bytes == theirs_bytes:
                merged_bytes = ours_bytes
            
            # Case 5: They changed, we didn't
            elif ours_bytes == base_bytes:
                merged_bytes = theirs_bytes
                print(f"  {f}: using 'theirs' version")
            
            # Case 6: We changed, they didn't
            elif theirs_bytes == base_bytes:
                merged_bytes = ours_bytes
                print(f"  {f}: using 'ours' version")
            
            # Case 7: CONFLICT
            else:
                conflict_occurred = True
                print(f"  {f}: CONFLICT (both modified)")
                if is_text:
                    try:
                        conflict_content = (
                            f"<<<<<<< HEAD (Branch: {current_branch})\n"
                            f"{ours_bytes.decode('utf-8')}\n"
                            f"=======\n"
                            f"{theirs_bytes.decode('utf-8')}\n"
                            f">>>>>>> {other_branch}\n"
                        )
                        merged_bytes = conflict_content.encode('utf-8')
                    except UnicodeDecodeError:
                        is_text = False # Fallback to binary
                
                if not is_text:
                    # Binary conflict, just write "ours" and log
                    merged_bytes = ours_bytes
                    print(f"  {f}: Binary conflict! Kept 'ours' version.")
                
                # Save your JSON conflict file for reference
                os.makedirs(merge_dir, exist_ok=True)
                conflict_file = os.path.join(merge_dir, f.replace(os.sep, "_") + ".json")
                conflict_json = {
                    "file": f,
                    "status": "conflict",
                    "base": base64.b64encode(base_bytes).decode("utf-8") if base_bytes is not None else None,
                    "ours": base64.b64encode(ours_bytes).decode("utf-8"),
                    "theirs": base64.b64encode(theirs_bytes).decode("utf-8")
                }
                with open(conflict_file, "w", encoding="utf-8") as mf:
                    json.dump(conflict_json, mf, indent=2, ensure_ascii=False)

            # Write merged bytes to working dir and stage it
            Path(abs_path).write_bytes(merged_bytes)
            self.index.add_file(f, calculate_hash(merged_bytes), "text" if is_text else "binary")


        # --- NEW: Final step ---
        if conflict_occurred:
            # STOP. DO NOT COMMIT.
            # Save the merge state
            with open(merge_head_path, "w") as f:
                f.write(other_head)
            print("\nAutomatic merge failed. Conflicts detected.")
            print(f"Conflict markers have been written to: {self.working_dir}")
            print(f"Conflict details (JSON) saved in: {merge_dir}")
            print("Please resolve the conflicts, then run 'gible add <file>' on each resolved file.")
            print("Finally, run 'gible commit' to finalize the merge.")
        else:
            # NO CONFLICTS. Create the merge commit automatically.
            print("\nAutomatic merge successful. Creating merge commit...")
            self.commit(
                f"Merge branch '{other_branch}' into '{current_branch}'", 
                merge_parents=[current_head, other_head]
            )
            self.switch_branch(current_branch, silent=True) # Checkout the new commit

    def get_commit_tree(self, commit_oid: Optional[str]) -> dict:
        if not commit_oid:
            return {}
        try:
            commit_obj = self._get_full_commit(commit_oid)
            return commit_obj.get("files", {})
        except FileNotFoundError:
            return {}

    # -------------------------
    # Checkout
    # -------------------------
    def checkout(self, commit_oid: Optional[str]):
        if commit_oid is None:
            # This is a new branch with no commits
            # We should clear the working dir (of tracked files)
            print("Checking out empty branch. (Note: un-tracked files remain)")
            # A more robust solution would be needed here,
            # but for now we do nothing and let the index be empty.
            self.index.clear()
            return

        files_map = self.get_commit_tree(commit_oid)
        if not files_map:
            print(f"Checked out empty commit {commit_oid[:8]}")
            return
            
        # Get all files in current working dir (that are not .gible)
        current_files = set()
        for root, dirs, files in os.walk(self.working_dir, topdown=True):
            dirs[:] = [d for d in dirs if d != GIBLE_REPO_DIR]
            for name in files:
                rel = os.path.relpath(os.path.join(root, name), self.working_dir)
                current_files.add(rel)

        # Write files from commit
        for filepath, entry in files_map.items():
            obj_type, oid = entry
            if obj_type == "base":
                data = load_object(self.repo_path, oid, "base")
            else:
                data = self.reconstruct_file_bytes(commit_oid, filepath)
            abs_path = os.path.join(self.working_dir, filepath)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            Path(abs_path).write_bytes(data)
            if filepath in current_files:
                current_files.remove(filepath)
        
        # Remove files that are in current_files but not in files_map
        for f in current_files:
            abs_path = os.path.join(self.working_dir, f)
            if os.path.exists(abs_path):
                os.remove(abs_path)

        print(f"Checked out commit {commit_oid[:8]}")

    # -------------------------
    # Status
    # -------------------------
    def status(self):
        metadata = self.load_metadata()
        print(f"On branch: {metadata.get('current_branch', 'master')}")
        
        merge_head_path = os.path.join(self.repo_path, MERGE_HEAD_FILE)
        if os.path.exists(merge_head_path):
            print("\nMerge in progress.")
            print("Resolve conflicts, then 'gible add' and 'gible commit'.")
            merge_dir = os.path.join(self.repo_path, MERGE_CONFLICT_DIR)
            if os.path.exists(merge_dir):
                print("Conflicts:")
                for f in os.listdir(merge_dir):
                    print(f"  {f.replace('_', os.sep).replace('.json', '')}")

        staged = self.index.get_all()
        if not staged:
            print("\nNo files staged")
        else:
            print("\nStaged files:")
            for f, info in staged.items():
                print(f"  {f} ({info.get('mode')})")
        
        # TODO: Add 'unstaged changes' and 'untracked files'
        # This would require comparing index vs working dir
        # and parent commit vs index.


# -------------------------
# CLI
# -------------------------
def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py <command> [args...]")
        print("Commands: init, add, rm, commit, branch, switch, merge, status, checkout")
        sys.exit(1)

    cmd = sys.argv[1]
    
    if cmd == "init":
        repo = GibleRepository(os.getcwd())
        repo.init()
        sys.exit(0)

    # All other commands require an existing repo
    repo = GibleRepository(os.getcwd())
    if not repo.is_repo():
        print("Error: Not a Gible repository. Run 'gible init' first.")
        sys.exit(1)

    if cmd == "add":
        if len(sys.argv) < 3:
            print("Usage: add <path>")
        else:
            repo.add(sys.argv[2])
            
    elif cmd == "rm":
        if len(sys.argv) < 3:
            print("Usage: rm <path>")
        else:
            repo.rm(sys.argv[2])
            
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
        
    elif cmd == "checkout":
        if len(sys.argv) < 3:
            print("Usage: checkout <commit_oid_or_branch_name>")
        else:
            target = sys.argv[2]
            metadata = repo.load_metadata()
            # Check if it's a branch name
            if target in metadata['branches']:
                repo.switch_branch(target)
            else:
                # Assume it's a commit OID
                try:
                    repo.checkout(target)
                    # Detached HEAD state
                    print(f"HEAD is now at {target[:8]}. You are in 'detached HEAD' state.")
                    metadata['head'] = target
                    metadata['current_branch'] = None # Or 'detached'
                    repo.save_metadata(metadata)
                except Exception as e:
                    print(f"Error: Could not checkout '{target}': {e}")
                    
    else:
        print(f"Unknown command: {cmd}")

if __name__ == "__main__":
    main()