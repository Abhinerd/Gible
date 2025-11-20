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
from typing import List, Tuple, Dict, Optional, Set
import bsdiff4
import uuid
import base64
import tempfile

# -------------------------
# Configuration
# -------------------------
GIBLE_REPO_DIR = ".gible"
OBJECTS_DIR = "objects"
INDEX_FILE = "index.json"
METADATA_FILE = "metadata.json"
CONFIG_FILE = "config.json"

# -------------------------
# Low level util
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
# Text diff handling
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
        self.output_buffer: List[str] = [] # Add this line

    # -------------------------
    # Initialization
    # -------------------------
    def init(self):
        if os.path.exists(self.repo_path):
            self._log(f"Repository already initialized at {self.repo_path}")
            return {"success": False, "message": "Repository already initialized."} # Modified
        os.makedirs(self.objects_path, exist_ok=True)
        initial_config = {
            "version": "0.5.0-deletion-support",
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
        self._log(f"Initialized Gible repository at {self.repo_path}")
        return {"success": True, "message": "Repository initialized successfully."} # Modified
    
    def _log(self, message: str):
        if hasattr(self, 'output_buffer'): # Check if running in UI mode
            self.output_buffer.append(message)
        else:
            self._log(message)
    
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
        if not isinstance(oid, str): # Add this type check
            raise ValueError(f"Invalid commit OID type: Expected string, got {type(oid).__name__} ({oid})")
        
        try:
            commit_bytes = load_object(self.repo_path, oid, "commit")
            return json.loads(commit_bytes.decode('utf-8'))
        except FileNotFoundError:
            metadata = self.load_metadata()
            meta_entry = metadata["commits"].get(oid)
            if not meta_entry:
                raise FileNotFoundError(f"Commit object {oid} not found in metadata or as file.")
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
    def reconstruct_file_bytes(self, commit_oid: str, filepath: str) -> Optional[bytes]:
        """
        Walk back from commit_oid through parents collecting chain entries for filepath.
        Returns:
          - bytes: reconstructed content
          - None: file was deleted (deleted entry encountered)
        Raises:
          - FileNotFoundError: file never present in history reachable from commit_oid
        """
        chain: List[Tuple[str, Optional[str]]] = []
        current_oid = commit_oid
        while current_oid:
            commit_obj = self._get_full_commit(current_oid)
            files_map = commit_obj.get("files", {})
            if filepath in files_map:
                entry = files_map[filepath]
                chain.append((entry[0], entry[1]))
            parent = commit_obj.get("parent")
            if isinstance(parent, list):
                parent = parent[0]  # for reconstruction choose first parent
            current_oid = parent
        if not chain:
            raise FileNotFoundError(f"File '{filepath}' not present in commit {commit_oid}")
        # chain holds history from newest->oldest; reverse to apply from base forward
        chain.reverse()
        base_type, base_oid = chain[0]
        # If the first entry is a deletion, file was deleted in the oldest recorded entry -> treat as deleted
        if base_type == "deleted":
            return None
        # load base content
        result = load_object(self.repo_path, base_oid, "base") if base_type == "base" else load_object(self.repo_path, base_oid, base_type)
        for obj_type, oid in chain[1:]:
            if obj_type == "deleted":
                # deletion recorded later in history -> file removed
                return None
            elif obj_type == "base":
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
            self._log(f"Error: Path not found: {filepath}")
            return {"success": False, "message": f"Path not found: {filepath}"} # Modified
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
            self._log(f"Staged: {rel} (mode: {mode})")
            return {"success": True, "message": f"Staged: {filepath}"} # Modified

    # -------------------------
    # Commit
    # -------------------------
    def commit(self, message: str):
        metadata = self.load_metadata()
        head = metadata.get("head")
        current_branch = metadata.get("current_branch", "master")
        staged = self.index.get_all()

        # Automatically detect previously tracked files that are now missing on disk
        previously_tracked_files = set()
        if head:
            previously_tracked_files = set(self.get_commit_tree(head).keys())
        missing_files = {f for f in previously_tracked_files if not os.path.exists(os.path.join(self.working_dir, f))}

        # Combine staged files + missing files
        combined_files = staged.copy()
        for f in missing_files:
            if f not in combined_files:
                combined_files[f] = {"mode": "text"}  # mode doesn't matter, it's deleted

        if not combined_files:
            self._log("No changes staged or detected. Nothing to commit.")
            # This is the return value that was causing issues if mistakenly stored
            return {"success": False, "message": "No changes staged or detected. Nothing to commit."}

        new_files_map: Dict[str, List[Optional[str]]] = {}
        for filepath, info in combined_files.items():
            abs_path = os.path.join(self.working_dir, filepath)

            # ---- handle deleted file on disk: record deletion ----
            if not os.path.exists(abs_path):
                new_files_map[filepath] = ["deleted", None]
                self._log(f"  {filepath}: deleted")
                continue

            # file exists on disk -> normal processing
            current_bytes = Path(abs_path).read_bytes()
            is_text = (info.get("mode") == "text")
            prev_entry = None
            if head:
                try:
                    full_commit = self._get_full_commit(head)
                    prev_entry = full_commit.get("files", {}).get(filepath)
                except FileNotFoundError:
                    prev_entry = None

            # if no previous recorded entry -> store base
            if prev_entry is None:
                oid = save_object(self.repo_path, current_bytes, "base")
                new_files_map[filepath] = ["base", oid]
                self._log(f"  {filepath}: stored base ({oid[:8]})")
            else:
                # reconstruct last content; reconstruct may return None if file was deleted in history
                try:
                    last_bytes = self.reconstruct_file_bytes(head, filepath)
                except FileNotFoundError:
                    last_bytes = None

                # treat last_bytes None as "no previous content" (store base)
                if last_bytes is None:
                    oid = save_object(self.repo_path, current_bytes, "base")
                    new_files_map[filepath] = ["base", oid]
                    self._log(f"  {filepath}: stored base ({oid[:8]})")
                    continue

                if is_text:
                    diff_bytes = generate_text_diff(last_bytes, current_bytes)
                    if not json.loads(diff_bytes.decode('utf-8')):
                        new_files_map[filepath] = prev_entry
                        self._log(f"  {filepath}: no changes (skipped)")
                    else:
                        oid = save_object(self.repo_path, diff_bytes, "diff")
                        new_files_map[filepath] = ["diff", oid]
                        self._log(f"  {filepath}: stored text diff ({oid[:8]})")
                else:
                    bin_diff = generate_binary_diff(last_bytes, current_bytes)
                    if len(bin_diff) < len(current_bytes):
                        oid = save_object(self.repo_path, bin_diff, "diff")
                        new_files_map[filepath] = ["diff", oid]
                        self._log(f"  {filepath}: stored binary diff ({oid[:8]})")
                    else:
                        oid = save_object(self.repo_path, current_bytes, "base")
                        new_files_map[filepath] = ["base", oid]
                        self._log(f"  {filepath}: stored binary base ({oid[:8]})")

            commit_obj = {
                "parent": head, # head is a string or None, which is fine
                "files": new_files_map,
                "message": message,
                "author": self.load_config().get("author", "unknown"),
                "timestamp": datetime.now().isoformat()
            }
            
            commit_oid = self._write_commit_object(commit_obj) # This returns a string OID
            # The _write_commit_object *already* updates metadata["head"] and metadata["branches"][current_branch]
            # So there's no need for commit() to do it again here.

            self._log(f"[{current_branch}] {message}")
            self._log(f"  commit {commit_oid}")
            self.index.clear()
            self._log("Staging area cleared.")
            return {"success": True, "commit_oid": commit_oid, "message": f"Committed: {commit_oid[:8]}"}


    # -------------------------
    # Branch utilities / ancestors
    # -------------------------
    
    def _all_ancestors(self, oid: Optional[str]) -> Set[str]:
        """Return set of all ancestor oids including oid itself."""
        result: Set[str] = set()
        if not oid:
            return result
        q = [oid]
        while q:
            x = q.pop()
            if x is None or x in result:
                continue
            result.add(x)
            try:
                commit = self._get_full_commit(x)
                parents = commit.get("parent")
                if parents:
                    if isinstance(parents, list):
                        for p in parents:
                            if p is not None:
                                q.append(p)
                    else:
                        if parents is not None:
                            q.append(parents)
            except FileNotFoundError:
                # broken commit chain; ignore
                continue
        return result
    
    def create_branch(self, name: str):
        metadata = self.load_metadata()
        if name in metadata['branches']:
            self._log(f"Branch '{name}' already exists")
            return {"success": False, "message": f"Branch '{name}' already exists"} # Modified
        metadata['branches'][name] = metadata['head']
        self.save_metadata(metadata)
        self._log(f"Branch '{name}' created at {metadata['head'][:8] if metadata['head'] else 'None'}")
        return {"success": True, "message": f"Branch '{name}' created."} # Modified
    
    def switch_branch(self, name: str, silent: bool = False):
        metadata = self.load_metadata()
        if name not in metadata['branches']:
            if not silent: self._log(f"Branch '{name}' does not exist")
            return {"success": False, "message": f"Branch '{name}' does not exist"}

        metadata['current_branch'] = name
        head_commit = metadata['branches'][name] # <--- PROBLEM POINT 1

        # Update main HEAD to point to branch tip
        metadata['head'] = head_commit # <--- PROBLEM POINT 2 (if head_commit is a dict)

        if head_commit: # This check is good
            self.restore_commit(head_commit, silent=True) # <--- PROBLEM POINT 3 (if head_commit is a dict)

        self.save_metadata(metadata)
        if not silent: self._log(f"Switched to branch '{name}'")
        return {"success": True, "message": f"Switched to branch '{name}'"}

    def _is_ancestor(self, ancestor: Optional[str], descendant: Optional[str]) -> bool:
        if not ancestor or not descendant:
            return False
        if ancestor == descendant:
            return True
        return ancestor in self._all_ancestors(descendant)

    def _find_common_ancestor(self, oid1: Optional[str], oid2: Optional[str]) -> Optional[str]:
        if not oid1 or not oid2:
            return None
        anc1 = self._all_ancestors(oid1)
        q = [oid2]
        visited = set()
        while q:
            x = q.pop(0)
            if x is None or x in visited:
                continue
            if x in anc1:
                return x
            visited.add(x)
            try:
                commit = self._get_full_commit(x)
                parents = commit.get("parent")
                if parents:
                    if isinstance(parents, list):
                        for p in parents:
                            if p is not None:
                                q.append(p)
                    else:
                        if parents is not None:
                            q.append(parents)
            except FileNotFoundError:
                continue
        return None

    # -------------------------
    # 3-way text merge helper
    # -------------------------
    def three_way_merge_text(self, base_lines: List[str], ours_lines: List[str], theirs_lines: List[str]) -> Tuple[str, bool]:
        sm_ours = SequenceMatcher(None, base_lines, ours_lines)
        sm_theirs = SequenceMatcher(None, base_lines, theirs_lines)

        modified_ours = []
        modified_theirs = []

        for tag, i1, i2, j1, j2 in sm_ours.get_opcodes():
            if tag != "equal":
                modified_ours.append((i1, i2, ours_lines[j1:j2]))

        for tag, i1, i2, j1, j2 in sm_theirs.get_opcodes():
            if tag != "equal":
                modified_theirs.append((i1, i2, theirs_lines[j1:j2]))

        boundaries = {0, len(base_lines)}
        for i1, i2, _ in modified_ours:
            boundaries.add(i1); boundaries.add(i2)
        for i1, i2, _ in modified_theirs:
            boundaries.add(i1); boundaries.add(i2)
        sorted_bounds = sorted(boundaries)

        def find_covering(seg_list, a, b):
            for i1, i2, chunk in seg_list:
                if i1 <= a and b <= i2:
                    return chunk
            return None

        result_lines: List[str] = []
        conflict = False

        for k in range(len(sorted_bounds) - 1):
            a = sorted_bounds[k]
            b = sorted_bounds[k+1]
            base_seg = base_lines[a:b]
            ours_seg = find_covering(modified_ours, a, b)
            theirs_seg = find_covering(modified_theirs, a, b)

            if ours_seg is None and theirs_seg is None:
                result_lines.extend(base_seg)
            elif ours_seg is not None and theirs_seg is None:
                result_lines.extend(ours_seg)
            elif ours_seg is None and theirs_seg is not None:
                result_lines.extend(theirs_seg)
            else:
                if ours_seg == theirs_seg:
                    result_lines.extend(ours_seg)
                else:
                    conflict = True
                    result_lines.append("<<<<<<< HEAD\n")
                    result_lines.extend(ours_seg)
                    result_lines.append("=======\n")
                    result_lines.extend(theirs_seg)
                    result_lines.append(">>>>>>> MERGE_BRANCH\n")

        return "".join(result_lines), conflict

    # -------------------------
    # Merge
    # -------------------------
    def merge_branch(self, other_branch: str):
        metadata = self.load_metadata()
        if other_branch not in metadata['branches']:
            self._log(f"Branch '{other_branch}' does not exist")
            return
        current_branch = metadata.get("current_branch", "master")
        current_head = metadata['branches'].get(current_branch)
        other_head = metadata['branches'][other_branch]

        if current_head == other_head:
            self._log("Already up-to-date.")
            return {"success": True, "message": "Already up-to-date."} # Modified

        if other_head and self._is_ancestor(other_head, current_head):
            try:
                commit_obj = self._get_full_commit(other_head)
                msg = commit_obj.get("message", "<no message>")
            except Exception:
                meta = metadata.get("commits", {}).get(other_head, {})
                msg = meta.get("message", "<no message>")
            self._log(f"Branch '{current_branch}' already includes '{other_branch}' ({msg} @ {other_head[:8]}).")
            return {"success": True, "message": f"Branch '{current_branch}' already includes '{other_branch}'."} # Modified

        if current_head and self._is_ancestor(current_head, other_head):
            self._log(f"Fast-forwarding '{current_branch}' to '{other_branch}'...")
            self.restore_commit(other_head) # Keep this as is for now for visual feedback during fast-forward
            metadata['branches'][current_branch] = other_head
            metadata['head'] = other_head
            self.save_metadata(metadata)
            self._log(f"Fast-forwarded {current_branch} -> {other_head[:8]}")
            return {"success": True, "message": f"Fast-forwarded to {other_branch}."} # Modified

        base_head = self._find_common_ancestor(current_head, other_head)
        self._log(f"Merging '{other_branch}' ({other_head[:8] if other_head else 'None'}) into '{current_branch}' ({current_head[:8] if current_head else 'None'})")
        self._log(f"Common ancestor: {base_head[:8] if base_head else 'None'}")

        files_base = self.get_commit_tree(base_head) if base_head else {}
        files_current = self.get_commit_tree(current_head) if current_head else {}
        files_other = self.get_commit_tree(other_head) if other_head else {}

        all_files = set(files_base.keys()) | set(files_current.keys()) | set(files_other.keys())

        conflict_occurred = False
        merge_id = str(uuid.uuid4())
        merge_dir = os.path.join(self.repo_path, "merge", merge_id)
        if os.path.exists(merge_dir):
            shutil.rmtree(merge_dir)
        os.makedirs(merge_dir, exist_ok=True)

        merged_files: Dict[str, List[Optional[str]]] = {}

        for f in all_files:
            base_entry = files_base.get(f)
            ours_entry = files_current.get(f)
            theirs_entry = files_other.get(f)

            # Determine deletion presence quickly from entries
            base_deleted = (base_entry is not None and base_entry[0] == "deleted")
            ours_deleted = (ours_entry is not None and ours_entry[0] == "deleted")
            theirs_deleted = (theirs_entry is not None and theirs_entry[0] == "deleted")

            # reconstruct bytes (None signals deleted)
            try:
                base_bytes = None if base_entry is None else (None if base_entry[0] == "deleted" else (load_object(self.repo_path, base_entry[1], "base") if base_entry[0] == "base" else self.reconstruct_file_bytes(base_head, f)))
            except Exception:
                base_bytes = None
            try:
                ours_bytes = None if ours_entry is None else (None if ours_entry[0] == "deleted" else self.reconstruct_file_bytes(current_head, f))
            except Exception:
                ours_bytes = None
            try:
                theirs_bytes = None if theirs_entry is None else (None if theirs_entry[0] == "deleted" else self.reconstruct_file_bytes(other_head, f))
            except Exception:
                theirs_bytes = None

            # HANDLE: both deleted or absent
            if (ours_entry is None or ours_bytes is None) and (theirs_entry is None or theirs_bytes is None):
                # both deleted/absent -> omit from merged_files (deletion wins)
                # ensure file removed from working tree
                try:
                    target = os.path.join(self.working_dir, f)
                    if os.path.exists(target): os.remove(target)
                except Exception:
                    pass
                continue

            # CASE: ours deleted, theirs not
            if (ours_entry is None or ours_bytes is None) and (theirs_entry is not None and theirs_bytes is not None):
                # If theirs didn't change relative to base -> deletion wins
                if base_bytes is not None and theirs_bytes == base_bytes:
                    # deletion wins -> remove file
                    try:
                        t = os.path.join(self.working_dir, f)
                        if os.path.exists(t): os.remove(t)
                    except Exception:
                        pass
                    continue
                else:
                    # conflict: deleted by us, modified by them
                    conflict_occurred = True
                    conflict_file = os.path.join(merge_dir, f.replace(os.sep, "_") + ".json")
                    os.makedirs(os.path.dirname(conflict_file), exist_ok=True)
                    conflict_json = {"file": f, "status": "conflict", "base": base_bytes.decode('utf-8') if base_bytes and is_text_content(base_bytes) else (base64.b64encode(base_bytes).decode() if base_bytes else None), "ours": None, "theirs": theirs_bytes.decode('utf-8') if theirs_bytes and is_text_content(theirs_bytes) else (base64.b64encode(theirs_bytes).decode() if theirs_bytes else None)}
                    with open(conflict_file, "w", encoding="utf-8") as mf:
                        json.dump(conflict_json, mf, indent=2, ensure_ascii=False)
                    # keep theirs in working tree for manual resolution
                    if theirs_bytes is not None:
                        Path(os.path.join(self.working_dir, f)).write_bytes(theirs_bytes)
                        merged_files[f] = ["base", save_object(self.repo_path, theirs_bytes, "base")]
                    continue

            # CASE: theirs deleted, ours not
            if (theirs_entry is None or theirs_bytes is None) and (ours_entry is not None and ours_bytes is not None):
                # If ours didn't change relative to base -> deletion wins
                if base_bytes is not None and ours_bytes == base_bytes:
                    try:
                        t = os.path.join(self.working_dir, f)
                        if os.path.exists(t): os.remove(t)
                    except Exception:
                        pass
                    continue
                else:
                    # conflict: modified by us, deleted by them
                    conflict_occurred = True
                    conflict_file = os.path.join(merge_dir, f.replace(os.sep, "_") + ".json")
                    os.makedirs(os.path.dirname(conflict_file), exist_ok=True)
                    conflict_json = {"file": f, "status": "conflict", "base": base_bytes.decode('utf-8') if base_bytes and is_text_content(base_bytes) else (base64.b64encode(base_bytes).decode() if base_bytes else None), "ours": ours_bytes.decode('utf-8') if ours_bytes and is_text_content(ours_bytes) else (base64.b64encode(ours_bytes).decode() if ours_bytes else None), "theirs": None}
                    with open(conflict_file, "w", encoding="utf-8") as mf:
                        json.dump(conflict_json, mf, indent=2, ensure_ascii=False)
                    # keep ours in working tree
                    if ours_bytes is not None:
                        Path(os.path.join(self.working_dir, f)).write_bytes(ours_bytes)
                        merged_files[f] = ["base", save_object(self.repo_path, ours_bytes, "base")]
                    continue

            # BOTH SIDES HAVE CONTENT -> normal merge
            if ours_bytes is not None and theirs_bytes is not None:
                if is_text_content(ours_bytes) and is_text_content(theirs_bytes):
                    base_lines = base_bytes.decode("utf-8").splitlines(keepends=True) if base_bytes is not None else []
                    ours_lines = ours_bytes.decode("utf-8").splitlines(keepends=True)
                    theirs_lines = theirs_bytes.decode("utf-8").splitlines(keepends=True)

                    merged_text, local_conflict = self.three_way_merge_text(base_lines, ours_lines, theirs_lines)
                    merged_bytes = merged_text.encode("utf-8")
                    if local_conflict:
                        conflict_occurred = True
                        conflict_file = os.path.join(merge_dir, f.replace(os.sep, "_") + ".json")
                        os.makedirs(os.path.dirname(conflict_file), exist_ok=True)
                        conflict_json = {"file": f, "status": "conflict", "base": "".join(base_lines), "ours": "".join(ours_lines), "theirs": "".join(theirs_lines)}
                        with open(conflict_file, "w", encoding="utf-8") as mf:
                            json.dump(conflict_json, mf, indent=2, ensure_ascii=False)
                    Path(os.path.join(self.working_dir, f)).write_bytes(merged_bytes)
                    merged_files[f] = ["base", save_object(self.repo_path, merged_bytes, "base")]
                else:
                    # binary or mixed
                    if ours_bytes == theirs_bytes:
                        merged_files[f] = ["base", save_object(self.repo_path, ours_bytes, "base")]
                    else:
                        conflict_occurred = True
                        conflict_file = os.path.join(merge_dir, f.replace(os.sep, "_") + ".json")
                        os.makedirs(os.path.dirname(conflict_file), exist_ok=True)
                        conflict_json = {"file": f, "status": "conflict", "base": base64.b64encode(base_bytes).decode() if base_bytes else None, "ours": base64.b64encode(ours_bytes).decode(), "theirs": base64.b64encode(theirs_bytes).decode()}
                        with open(conflict_file, "w", encoding="utf-8") as mf:
                            json.dump(conflict_json, mf, indent=2, ensure_ascii=False)
                        Path(os.path.join(self.working_dir, f)).write_bytes(ours_bytes)
                        merged_files[f] = ["base", save_object(self.repo_path, ours_bytes, "base")]

        # If conflicts occurred: prompt user
        if conflict_occurred:
            self._log("\nAutomatic merge produced conflicts.")
            self._log(f"Conflict details saved under: {merge_dir}")
            return {"success": False, "message": "Merge aborted. Conflicts detected.", "conflicts": True, "merge_dir": merge_dir} # This return is fine.
    
        # If no conflicts, create merge commit
        merge_commit_obj = {
            "parent": [current_head, other_head],
            "files": merged_files,
            "message": f"Merge branch {other_branch} into {current_branch}",
            "author": self.load_config().get("author", "unknown"),
            "timestamp": datetime.now().isoformat()
        }
        
        # If successful, commit_oid is a string and updates metadata correctly
        commit_oid = self._write_commit_object(merge_commit_obj)
        self._log(f"Merge commit created: {commit_oid} {'(with conflicts)' if conflict_occurred else '(no conflicts)'}")

        metadata['branches'][current_branch] = commit_oid
        metadata['head'] = commit_oid
        self.save_metadata(metadata)
        self._log(f"Updated {current_branch} -> {commit_oid[:8]}")
        return {"success": True, "message": "Merge completed successfully."} # Modified

    # -------------------------
    # Helpers: commit tree, restore (was checkout)
    # -------------------------
    def get_commit_tree(self, commit_oid: Optional[str]) -> dict:
        if not commit_oid:
            return {}
        try:
            commit_obj = self._get_full_commit(commit_oid)
            return commit_obj.get("files", {})
        except FileNotFoundError:
            return {}

    def restore_commit(self, commit_oid: str, silent: bool = False):    
        """
        Restore (rollback) working directory to match commit_oid.
        Handles 'deleted' entries by removing files from disk.
        """
        files_map = self.get_commit_tree(commit_oid)

        # Determine currently tracked files (from current HEAD in metadata)
        metadata = self.load_metadata()
        current_head = metadata.get("head")
        current_tracked = set()
        if current_head:
            current_tracked = set(self.get_commit_tree(current_head).keys())

        # Remove tracked files that won't be in the new commit (Option C behavior)
        for f in list(current_tracked):
            if f not in files_map:
                abs_path = os.path.join(self.working_dir, f)
                # safety: don't touch .gible
                if GIBLE_REPO_DIR in Path(abs_path).parts:
                    continue
                if os.path.exists(abs_path):
                    try:
                        os.remove(abs_path)
                    except Exception:
                        pass
                    # try removing empty parent directories
                    parent = os.path.dirname(abs_path)
                    while parent and parent != self.working_dir and parent.startswith(self.working_dir):
                        try:
                            if not os.listdir(parent):
                                os.rmdir(parent)
                            else:
                                break
                        except Exception:
                            break
                        parent = os.path.dirname(parent)

        # Write files from commit (overwrites existing or creates new; handles 'deleted')
        for filepath, entry in files_map.items():
            obj_type, oid = entry[0], entry[1]

            abs_path = os.path.join(self.working_dir, filepath)
            # Create parent dirs
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)

            if obj_type == "deleted":
                # ensure file removed
                if os.path.exists(abs_path):
                    try:
                        os.remove(abs_path)
                    except Exception:
                        pass
                continue

            if obj_type == "base":
                data = load_object(self.repo_path, oid, "base")
                Path(abs_path).write_bytes(data)
                continue

            if obj_type == "diff":
                try:
                    data = self.reconstruct_file_bytes(commit_oid, filepath)
                except FileNotFoundError:
                    data = None
                if data is None:
                    # resolved to deletion
                    if os.path.exists(abs_path):
                        try:
                            os.remove(abs_path)
                        except Exception:
                            pass
                else:
                    Path(abs_path).write_bytes(data)
                continue

        
        if not silent: # Only log if not silent
            self._log(f"Restored commit {commit_oid[:8]}")
        return {"success": True, "message": f"Restored commit {commit_oid[:8]}"} # Modified

    # -------------------------
    # Status
    # -------------------------
    def status(self):
        metadata = self.load_metadata()
        self._log(f"On branch: {metadata.get('current_branch', 'master')}")
        staged = self.index.get_all()
        if not staged:
            self._log("No files staged")
        else:
            self._log("Staged files:")
            for f, info in staged.items():
                self._log(f"  {f} ({info.get('mode')})")

    # -------------------------
    # Destroy repository
    # -------------------------
    def destroy(self):
        if not self.is_repo():
            self._log("Not a Gible repository. Nothing to destroy.")
            return {"success": False, "message": "Not a Gible repository. Nothing to destroy."} # Modified

        # Remove the confirmation prompt, UI will handle it
        # confirm = input(f"This will permanently delete the Gible repository at {self.repo_path}.\nAre you sure? (y/n): ").strip().lower()
        # if confirm == 'y':
        try:
            shutil.rmtree(self.repo_path)
            self._log(f"Gible repository at {self.repo_path} has been destroyed.")
            return {"success": True, "message": f"Gible repository at {self.repo_path} has been destroyed."} # Modified
        except Exception as e:
            self._log(f"Error destroying repository: {e}")
            return {"success": False, "message": f"Error destroying repository: {e}"} # Modified
        # else:
        #     self._log("Destroy operation cancelled.")
        #     return {"success": False, "message": "Destroy operation cancelled."} # Modified

    # -------------------------
    # Convenience: branches & logs
    # -------------------------
    
    def current_branch(self) -> str:
        metadata = self.load_metadata()
        return metadata.get("current_branch", "master")
    
    def list_branches(self):
        metadata = self.load_metadata()
        return list(metadata["branches"].keys()) # Modified

    def list_commits(self, branch_name: Optional[str] = None) -> List[Dict[str, str]]: # Modified signature
        metadata = self.load_metadata()
        head = metadata.get("head")
        if branch_name:
            head = metadata["branches"].get(branch_name)

        if head is None: # Check if head is None
            return [] # Return empty list if no commits

        # Add a check here just in case 'head' somehow got corrupted with a dict
        if not isinstance(head, str):
            self._log(f"Warning: Corrupted 'head' reference in metadata: {head}. Resetting to None.")
            metadata["head"] = None
            if branch_name:
                metadata["branches"][branch_name] = None
            self.save_metadata(metadata) # Save the corrected metadata
            return [] # Cannot list commits from a corrupted head

        commits_list: List[Dict[str, str]] = []

        current_commit_oid = head
        while current_commit_oid:
            # The type check in _get_full_commit will catch non-string parents.
            # But the primary head should be clean here.
            c = self._get_full_commit(current_commit_oid)
            commits_list.append({
                "oid": current_commit_oid,
                "message": c.get("message", ""),
                "timestamp": c.get("timestamp", ""),
                "author": c.get("author", "unknown"),
                "parent": c.get("parent")
            })
            parent = c.get("parent")
            if isinstance(parent, list):
                parent = parent[0]
            if parent is None: # Explicitly break if parent is None
                break
            # Ensure parent is a string for the next iteration
            if not isinstance(parent, str):
                self._log(f"Warning: Corrupted parent reference for commit {current_commit_oid}: {parent}. Terminating commit log.")
                break
            current_commit_oid = parent
        return commits_list

# -------------------------
# Test helper: construct repo & cause a same-line conflict + deletion test
# -------------------------
def run_merge_conflict_test():
    tmp = tempfile.mkdtemp(prefix="gible-test-")
    print("Test repo directory:", tmp)
    repo = GibleRepository(tmp)
    repo.init()

    # write base file and commit on master
    Path(os.path.join(tmp, "1.txt")).write_text("line1\nline2\nline3\n", encoding="utf-8")
    Path(os.path.join(tmp, "to_delete.txt")).write_text("delete me\n", encoding="utf-8")
    repo.add("1.txt")
    repo.add("to_delete.txt")
    repo.commit("base commit")

    # create branch 'feature'
    repo.create_branch("feature")
    repo.switch_branch("feature")
    # modify same line differently and commit
    Path(os.path.join(tmp, "1.txt")).write_text("line1\nfeature-modified-line2\nline3\n", encoding="utf-8")
    repo.add("1.txt")
    repo.commit("feature edits")

    # switch back to master and make a conflicting edit and commit and delete a file
    repo.switch_branch("master")
    Path(os.path.join(tmp, "1.txt")).write_text("line1\nmaster-modified-line2\nline3\n", encoding="utf-8")
    os.remove(os.path.join(tmp, "to_delete.txt"))  # delete file on disk
    repo.add("1.txt")
    # stage deletion by leaving to_delete.txt in index but absent on disk:
    # (index still has it from initial add; commit() will detect file missing and record deletion)
    repo.commit("master edits (and deletion)")

    # merge feature into master: should detect conflict
    print("\n=== Now merging 'feature' into 'master' (expected conflict) ===")
    repo.merge_branch("feature")

    print("\nCheck working copy (1.txt) for conflict markers and merge dir:")
    print("Working file:")
    print(Path(os.path.join(tmp, "1.txt")).read_text(encoding="utf-8"))
    print("Merge dir:", os.path.join(repo.repo_path, "merge"))
    print("Test done. Remove temp dir when finished:", tmp)

# # -------------------------
# # CLI
# # -------------------------
# def main():
#     if len(sys.argv) < 2:
#         print("Usage: python gible_base.py <command> [...]")
#         print("\nAvailable commands:")
#         print("  init            - Initialize a new Gible repository")
#         print("  add <path>      - Stage a file or directory for commit")
#         print("  commit <msg>    - Record staged changes")
#         print("  branch <name>   - Create a new branch")
#         print("  switch <name>   - Switch to a different branch")
#         print("  merge <name>    - Merge a branch into the current branch")
#         print("  status          - Show the working tree status")
#         print("  restore <id>    - Restore working dir to a specific commit (was checkout)")
#         print("  destroy         - Permanently delete the Gible repository")
#         print("  test-merge      - Run a pre-defined merge conflict test")
#         print("  list-branches   - List branches")
#         print("  log-commits     - Log commits of current branch")
#         sys.exit(1)

#     cmd = sys.argv[1]
#     repo = GibleRepository(os.getcwd())

#     if cmd == "init":
#         repo.init()
#     elif cmd == "add":
#         if len(sys.argv) < 3:
#             print("Usage: add <path>")
#         else:
#             repo.add(sys.argv[2])
#     elif cmd == "commit":
#         if len(sys.argv) < 3:
#             print("Usage: commit <message>")
#         else:
#             repo.commit(sys.argv[2])
#     elif cmd == "branch":
#         if len(sys.argv) < 3:
#             print("Usage: branch <name>")
#         else:
#             repo.create_branch(sys.argv[2])
#     elif cmd == "switch":
#         if len(sys.argv) < 3:
#             print("Usage: switch <branch>")
#         else:
#             repo.switch_branch(sys.argv[2])
#     elif cmd == "merge":
#         if len(sys.argv) < 3:
#             print("Usage: merge <branch>")
#         else:
#             repo.merge_branch(sys.argv[2])
#     elif cmd == "status":
#         repo.status()
#     elif cmd == "restore":
#         if len(sys.argv) < 3:
#             print("Usage: restore <commit_oid>")
#         else:
#             repo.restore_commit(sys.argv[2])
#     elif cmd == "test-merge":
#         run_merge_conflict_test()
#     elif cmd == "destroy":
#         repo.destroy()
#     elif cmd == "list-branches":
#         repo.list_branches()
#     elif cmd == "log-commits":
#         repo.list_commits()
#     else:
#         print(f"Unknown command: {cmd}")

# if __name__ == "__main__":
#     main()