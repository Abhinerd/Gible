import shutil
import sys
import zipfile
import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, simpledialog, filedialog
import tkinter.messagebox as messagebox
from pathlib import Path
import json
from functools import partial
import os

# Gible
from base import GibleRepository


# -------------------------------
# Persistent Repo Storage
# -------------------------------
GIBLE_HOME = Path.home() / "gible"
GIBLE_HOME.mkdir(exist_ok=True)

INFO_FILE = GIBLE_HOME / "info.json"


def load_repo_list():
    if INFO_FILE.exists():
        return json.loads(INFO_FILE.read_text())
    return []


def save_repo_list(repos):
    INFO_FILE.write_text(json.dumps(repos, indent=4))


# -------------------------------
# Fonts / Colors
# -------------------------------
repo_title_font = ("Lexend", 21, "bold")
repo_detail_font = ("Lexend", 14)
mono_font = ("Lexend", 16)

bg_color = "#010A15"
repo_card_color = "#6792a9"
text_color = "#cccccc"
subtext_color = "#B9E2E7"
hover_color = "#146acc"
editor_text_color = "#cccccc"


# -------------------------------
# Repo List Screen
# -------------------------------
class RepoListScreen(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master)
        self.configure(fg_color=bg_color)

        # Heading
        heading_frame = tk.Frame(self, bg=bg_color)
        heading_frame.pack(fill="x", padx=90, pady=(80, 10))

        heading = ctk.CTkLabel(
            heading_frame, text="REPOSITORIES", font=("Lexend", 50, "bold"),
            text_color=text_color, anchor="w"
        )
        heading.pack(side="left", anchor="w")

        # --- CHANGED: Added a frame for buttons to hold both Add and Import ---
        btn_frame = tk.Frame(heading_frame, bg=bg_color)
        btn_frame.pack(side="right", anchor="e")

        import_btn = ctk.CTkButton(
            btn_frame, text="Import", width=150, height=45,
            fg_color="#333333", hover_color=hover_color,
            font=("Lexend", 17, "bold"),
            command=self.import_repository # <--- New Command
        )
        import_btn.pack(side="right", padx=(10, 0))

        add_button = ctk.CTkButton(
            btn_frame, text="Add Folder", width=150, height=45,
            fg_color="#333333", hover_color=hover_color,
            font=("Lexend", 17, "bold"),
            command=self.add_repository
        )
        add_button.pack(side="right")
        # --------------------------------------------------------------------

        # Scroll area
        self.scrollable_frame = ctk.CTkScrollableFrame(
            self, fg_color=bg_color, border_width=0, corner_radius=0
        )
        self.scrollable_frame.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        self.refresh_repo_cards()

    # ----------------------------------------------------------------------
    # Import Logic
    # ----------------------------------------------------------------------
    def import_repository(self):
        # 1. Select ZIP file
        zip_path = filedialog.askopenfilename(
            title="Select Gible Repository (.zip)",
            filetypes=[("Zip Files", "*.zip")]
        )
        if not zip_path:
            return

        # 2. Select Destination Folder (Where to extract)
        dest_parent_folder = filedialog.askdirectory(title="Select Extraction Location")
        if not dest_parent_folder:
            return

        try:
            zip_path_obj = Path(zip_path)
            repo_name = zip_path_obj.stem # 'project.zip' -> 'project'
            target_dir = Path(dest_parent_folder) / repo_name

            # Prevent overwriting existing folders
            if target_dir.exists():
                messagebox.showerror("Error", f"A folder named '{repo_name}' already exists in that location.")
                return

            target_dir.mkdir()

            # 3. Extract
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(target_dir)

            # 4. Check if it's valid (Optional: handle flat zips vs nested zips)
            # If the user zipped the *contents* and not the folder, .gible might be at root.
            # If they zipped the folder, there might be a subfolder.
            # For simplicity, we register 'target_dir'.
            
            # 5. Add to Gible App
            repos = load_repo_list()
            if any(r["path"] == str(target_dir) for r in repos):
                messagebox.showinfo("Info", "Repository already tracked.")
            else:
                repos.append({
                    "name": repo_name,
                    "path": str(target_dir)
                })
                save_repo_list(repos)
                self.refresh_repo_cards()
                messagebox.showinfo("Success", f"Imported '{repo_name}' successfully.")

        except Exception as e:
            messagebox.showerror("Import Error", str(e))

    # ----------------------------------------------------------------------
    # NEW: Export Logic
    # ----------------------------------------------------------------------
    def export_repo(self, repo):
        # 1. Ask where to save the zip
        save_path = filedialog.asksaveasfilename(
            title="Export Repository",
            initialfile=f"{repo['name']}.zip",
            defaultextension=".zip",
            filetypes=[("Zip Files", "*.zip")]
        )
        if not save_path:
            return

        source_dir = Path(repo["path"])
        
        if not source_dir.exists():
            messagebox.showerror("Error", "Repository path not found.")
            return

        try:
            # shutil.make_archive expects the file path WITHOUT .zip extension for the first arg,
            # but asksaveasfilename gives us the full path WITH .zip.
            base_name = str(Path(save_path).parent / Path(save_path).stem)
            
            # root_dir is the directory we are zipping
            shutil.make_archive(base_name, 'zip', root_dir=source_dir)
            
            messagebox.showinfo("Success", f"Repository exported to:\n{save_path}")
        except Exception as e:
            messagebox.showerror("Export Error", str(e))

    # ----------------------------------------------------------------------

    def add_repository(self):
        folder = filedialog.askdirectory(title="Select Repository Folder")
        if not folder:
            return

        folder = Path(folder)
        repos = load_repo_list()

        if any(r["path"] == str(folder) for r in repos):
            messagebox.showinfo("Exists", "This repository is already added.")
            return

        repos.append({
            "name": folder.name,
            "path": str(folder)
        })
        save_repo_list(repos)
        self.refresh_repo_cards()

    # ----------------------------------------------------------------------

    def delete_repo(self, repo):
        # 1. Ask the user what they want to do with the physical files
        delete_from_disk = messagebox.askyesno(
            "Delete Repository",
            f"You are removing '{repo['name']}'.\n\n"
            "Do you also want to permanently delete the folder from your computer?\n\n"
            "YES = Delete entire folder (Files + History)\n"
            "NO  = Keep files, but delete Gible history (.gible)"
        )

        repo_path = Path(repo["path"])

        # ---------------------------------------------------------
        # OPTION A: Delete everything (Folder, Files, .gible)
        # ---------------------------------------------------------
        if delete_from_disk:
            # Extra safety check since this is destructive
            confirm = messagebox.askyesno(
                "Confirm Deletion", 
                f"Are you sure you want to delete:\n{repo_path}\n\nThis cannot be undone."
            )
            if not confirm:
                return # Cancel the whole operation

            try:
                if repo_path.exists():
                    shutil.rmtree(repo_path)
            except Exception as e:
                messagebox.showerror("Error", f"Could not delete folder:\n{e}")
                return

        # ---------------------------------------------------------
        # OPTION B: Keep files, but delete .gible (Un-initialize)
        # ---------------------------------------------------------
        else:
            gible_dir = repo_path / ".gible"
            if gible_dir.exists():
                try:
                    shutil.rmtree(gible_dir)
                except Exception as e:
                    messagebox.showwarning("Warning", f"Could not delete .gible folder:\n{e}")

        # ---------------------------------------------------------
        # FINAL: Remove from the App's JSON list
        # ---------------------------------------------------------
        repos = load_repo_list()
        # Filter out the repo that matches the path
        repos = [r for r in repos if r["path"] != repo["path"]]
        save_repo_list(repos)
        
        self.refresh_repo_cards()
    # ----------------------------------------------------------------------

    def refresh_repo_cards(self):
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()

        self.repo_list = load_repo_list()

        for repo in self.repo_list:
            self.create_repo_card(repo)

    # ----------------------------------------------------------------------

    def create_repo_card(self, repo):
        card = ctk.CTkFrame(self.scrollable_frame, fg_color=repo_card_color)
        card.pack(fill="x", padx=50, pady=(50, 20))

        title = ctk.CTkLabel(
            card,
            text=repo["name"].upper(),
            font=repo_title_font,
            text_color=text_color,
            anchor="w",
        )
        title.pack(anchor="nw", padx=10, pady=(10, 0))

        detail_label = ctk.CTkLabel(
            card,
            text=repo["path"],
            font=repo_detail_font,
            text_color=subtext_color,
            anchor="w"
        )
        detail_label.pack(anchor="nw", padx=10, pady=(5, 10))

        # Open
        for widget in [card, title, detail_label]:
            widget.bind("<Button-1>", partial(lambda e, r=repo: self.master.show_frame_with_repo(ExplorerEditorScreen, r)))

        # Right-click menu
        menu = tk.Menu(self, tearoff=0)
        # --- CHANGED: Added Export option ---
        menu.add_command(label="Export (.zip)", command=lambda r=repo: self.export_repo(r))
        menu.add_separator()
        menu.add_command(label="Delete", command=lambda r=repo: self.delete_repo(r))
        menu.add_command(label="Info", command=lambda r=repo: messagebox.showinfo(
            "Repository Info", f"Name: {r['name']}\nPath: {r['path']}"
        ))

        def show_menu(event, m=menu):
            m.tk_popup(event.x_root, event.y_root)

        for widget in [card, title, detail_label]:
            widget.bind("<Button-3>", show_menu)

# -------------------------------
# File Explorer + Editor Screen
# -------------------------------
class ExplorerEditorScreen(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master)
        self.configure(fg_color=bg_color)

        self.repo = None
        self.repo_path = None
        self.current_file_path = None  # Key for the dictionary

        # Dictionary to store { file_path_string : tk.Text_Widget_Instance }
        self.file_editors = {}
        self.active_editor = None  # The currently visible widget

        # Main Layout
        self.main_container = tk.Frame(self, bg=bg_color)
        self.main_container.pack(fill="both", expand=True)

        # --- Left Explorer ---
        self.explorer_left = tk.Frame(self.main_container, bg="#09364C", width=450, padx=30, pady=60)
        self.explorer_left.pack(side="left", fill="y")
        self.explorer_left.pack_propagate(False)

        self.file_tree = ttk.Treeview(self.explorer_left, show="tree")
        self.file_tree.pack(fill="both", expand=True)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#02202E", foreground=text_color,
                        rowheight=32, fieldbackground="#02202E", font=mono_font)
        style.map("Treeview", background=[("selected", hover_color)], foreground=[("selected", "#ffffff")])

        self.file_tree.bind("<<TreeviewSelect>>", self.load_file)

        # Back button
        self.back_btn = ctk.CTkButton(
            self.explorer_left, text="← Back to Repos",
            fg_color="#1D3441", hover_color=hover_color, corner_radius=5,font=mono_font,
            command=lambda: master.show_frame(RepoListScreen)
        )
        self.back_btn.pack(side="bottom", pady=(30,50))

        # --- Right Editor Area ---
        self.editor_right = tk.Frame(self.main_container, bg="#042A3A", padx=20)
        self.editor_right.pack(side="left", fill="both", expand=True)

        # Button Bar
        self.button_bar = tk.Frame(self.editor_right, bg="#042A3A")
        self.button_bar.pack(fill="x", pady=60)

        def add_btn(text, cmd):
            btn = ctk.CTkButton(self.button_bar, text=text, width=120,
                                fg_color="#1D3441", hover_color=hover_color,
                                command=cmd,
                                font=("Lexend",16, "bold"))
            btn.pack(side="left", padx=8)

        add_btn("Commit", self.commit_action)
        add_btn("History", self.history_action)
        add_btn("Rollback", self.rollback_action)
        add_btn("Branch", self.branch_action)
        add_btn("Switch", self.switch_branch_action)
        add_btn("Merge", self.merge_action)
        add_btn("Refresh", self.refresh_files)

        # Container for Text Widgets (The editors will be packed into this frame)
        self.editor_frame = tk.Frame(self.editor_right, bg="#042A3A")
        self.editor_frame.pack(fill="both", expand=True)

        # Keybinds
        if sys.platform == "darwin":
            master.bind_all("<Command-s>", self.save_file_shortcut)
            master.bind_all("<Command-z>", self.undo_action)
            master.bind_all("<Command-Shift-z>", self.redo_action)
        else:
            master.bind_all("<Control-s>", self.save_file_shortcut)
            master.bind_all("<Control-z>", self.undo_action)
            master.bind_all("<Control-y>", self.redo_action)

        # Right-Click bind
        self.file_tree.bind("<Button-3>", self.on_file_right_click)

    # ----------------------------------------------------------------------
    # Undo / Redo Handlers
    # ----------------------------------------------------------------------
    def undo_action(self, event=None):
        if self.active_editor and isinstance(self.active_editor, tk.Text):
            try:
                self.active_editor.edit_undo()
            except tk.TclError:
                pass  # Stack empty
        return "break"

    def redo_action(self, event=None):
        if self.active_editor and isinstance(self.active_editor, tk.Text):
            try:
                self.active_editor.edit_redo()
            except tk.TclError:
                pass  # Stack empty
        return "break"

    # ----------------------------------------------------------------------
    # File Loading Logic (The Core Fix)
    # ----------------------------------------------------------------------
    def load_file(self, event):
        """
        Triggered when a user clicks a file in the tree.
        Switches visibility to the specific Text widget for that file.
        """
        selection = self.file_tree.selection()
        if not selection:
            return

        item_id = selection[0]

        # Reconstruct Path from Treeview
        item_text = self.file_tree.item(item_id, "text")
        path_parts = [item_text]
        parent_id = self.file_tree.parent(item_id)
        while parent_id:
            parent_text = self.file_tree.item(parent_id, "text")
            path_parts.insert(0, parent_text)
            parent_id = self.file_tree.parent(parent_id)

        constructed_path = Path(*path_parts)

        # Convert to absolute system path
        try:
            relative_part = constructed_path.relative_to(self.repo_path.name)
            full_path = self.repo_path / relative_part
        except Exception:
            # Clicked on Root Folder or something unexpected
            return

        if not full_path.is_file():
            # If it's a folder, clear editor and show folder info
            self.current_file_path = None
            if self.active_editor:
                self.active_editor.pack_forget()
            lbl = tk.Label(self.editor_frame, text=f"# Folder: {full_path.name}",
                           bg="#02202E", fg="#555555", font=mono_font)
            lbl.pack(expand=True)
            self.active_editor = lbl
            return

        str_path = str(full_path)
        self.current_file_path = str_path

        # 1. Hide the currently active editor (if any)
        if self.active_editor:
            try:
                self.active_editor.pack_forget()
            except Exception:
                pass

        # 2. Check if we already have an editor for this file
        if str_path in self.file_editors:
            # Retrieve existing widget (preserves undo stack!)
            self.active_editor = self.file_editors[str_path]
            self.active_editor.pack(fill="both", expand=True, padx=(0,60), pady=(0,80))
            # Ensure focus so typing works immediately
            self.active_editor.focus_set()
        else:
            # 3. Create a NEW editor widget for this file
            try:
                content = full_path.read_text(encoding='utf-8')
                new_editor = tk.Text(
                    self.editor_frame, bg="#02202E", fg=editor_text_color,
                    font=mono_font, insertbackground=editor_text_color,
                    undo=True, maxundo=-1,  # Allow large undo
                    highlightthickness=0, bd=0, padx=20, pady=20
                )
                new_editor.insert("1.0", content)

                # Reset the undo stack so "inserting initial content" isn't the first undo
                new_editor.edit_reset()

                new_editor.pack(fill="both", expand=True, padx=(0,60), pady=(0,80))

                # Store it
                self.file_editors[str_path] = new_editor
                self.active_editor = new_editor
            except Exception as e:
                messagebox.showerror("Read Error", f"Could not read file:\n{e}")

    # ----------------------------------------------------------------------
    # Standard Operations
    # ----------------------------------------------------------------------

    def save_file_shortcut(self, event=None):
        self.save_current_file()
        return "break"

    def save_current_file(self):
        if not self.current_file_path or not isinstance(self.active_editor, tk.Text):
            messagebox.showinfo("Save", "No file selected.")
            return

        content = self.active_editor.get("1.0", "end-1c")  # Get text from active widget
        try:
            Path(self.current_file_path).write_text(content, encoding='utf-8')
            # Note: we keep the small popup to match original behaviour
            messagebox.showinfo("Saved", f"Saved: {Path(self.current_file_path).name}")
        except Exception as e:
            messagebox.showerror("Save Error", str(e))

    def refresh_files(self):
        # When refreshing (or switching branches), files on disk change.
        # We MUST destroy existing editors because their content/undo history
        # is now invalid relative to the new file system state.
        self.clear_editors()

        self.load_repo({"path": str(self.repo_path), "name": self.repo_path.name})
        messagebox.showinfo("Refreshed", "File structure updated.")

    def clear_editors(self):
        """Helper to destroy all open text widgets"""
        for path, widget in list(self.file_editors.items()):
            try:
                widget.destroy()
            except Exception:
                pass
        self.file_editors = {}
        # destroy any placeholder label if present
        if self.active_editor and not isinstance(self.active_editor, tk.Text):
            try:
                self.active_editor.destroy()
            except Exception:
                pass
        self.active_editor = None
        self.current_file_path = None

    def load_repo(self, repo_data):
        # Clear previous repo's editors from memory
        self.clear_editors()

        self.repo_path = Path(repo_data["path"])
        self.repo = GibleRepository(str(self.repo_path))

        if not self.repo.is_repo():
            init_result = self.repo.init()
            if not init_result["success"]:
                messagebox.showerror("Init Error", init_result["message"])
                return

        # Clear tree
        for item in self.file_tree.get_children():
            self.file_tree.delete(item)

        root = self.file_tree.insert("", "end", text=self.repo_path.name, open=True)

        def add_items(parent, path: Path):
            for entry in sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
                if entry.name.startswith("."):
                    continue  # Skip hidden
                node = self.file_tree.insert(parent, "end", text=entry.name, open=False)
                if entry.is_dir():
                    add_items(node, entry)

        if self.repo_path.exists():
            add_items(root, self.repo_path)

        # Show a placeholder label since no file is selected yet
        lbl = tk.Label(self.editor_frame, text="Select a file to edit",
                       bg="#02202E", fg="#97A0A4", font=mono_font)
        lbl.pack(expand=True)
        # We store this label as active_editor temporarily just so pack_forget works later
        self.active_editor = lbl

    # ----------------------------------------------------------------------
    # Context Menu & Gible Actions
    # ----------------------------------------------------------------------

    def on_file_right_click(self, event):
        item = self.file_tree.identify_row(event.y)
        if not item:
            return
        self.file_tree.selection_set(item)

        # Reconstruct path (same logic as in load_file)
        item_text = self.file_tree.item(item, "text")
        path_parts = [item_text]
        parent = self.file_tree.parent(item)
        while parent:
            pn = self.file_tree.item(parent)["text"]
            path_parts.insert(0, pn)
            parent = self.file_tree.parent(parent)

        constructed = Path(*path_parts)
        try:
            full_path = self.repo_path / constructed.relative_to(self.repo_path.name)
        except Exception:
            full_path = self.repo_path

        menu = tk.Menu(self, tearoff=0)
        if full_path.is_file():
            menu.add_command(label="Delete File", command=lambda: self.delete_file(item))
        elif full_path.is_dir():
            menu.add_command(label="Create File", command=lambda: self.create_file(full_path))
            menu.add_command(label="Delete Folder", command=lambda: self.delete_folder(full_path))
        menu.post(event.x_root, event.y_root)

    def _reconstruct_relative_and_full(self, item):
        """
        Helper that, given a tree item id, returns (relative_to_repo_working_dir_str, full_path(Path))
        Raises ValueError if path cannot be constructed.
        """
        name = self.file_tree.item(item, "text")
        rel = Path(name)
        parent = self.file_tree.parent(item)
        while parent:
            pn = self.file_tree.item(parent, "text")
            rel = Path(pn) / rel
            parent = self.file_tree.parent(parent)

        # rel starts with repo root name; convert to path relative to repo_path
        try:
            relative_to_repo = rel.relative_to(self.repo_path.name)
            full = self.repo_path / relative_to_repo
        except Exception:
            # If anything goes wrong, try to resolve relative to repo.working_dir if available
            full = (self.repo_path / rel.name) if rel.name else self.repo_path
            relative_to_repo = full.relative_to(self.repo_path)
        # produce path relative to repo.working_dir for repo.add
        try:
            repo_rel_for_add = str(full.relative_to(self.repo.working_dir))
        except Exception:
            # fallback to relative path inside repo_path
            repo_rel_for_add = str(full.relative_to(self.repo_path))
        return repo_rel_for_add, full

    def delete_file(self, item):
        """
        Delete the file on disk, stage the deletion in the repo, remove any open editor,
        and refresh the file tree.
        """
        try:
            repo_rel, full_path_to_delete = self._reconstruct_relative_and_full(item)
        except Exception as e:
            messagebox.showerror("Error", f"Path error: {e}")
            return

        filename = full_path_to_delete.name
        if not full_path_to_delete.exists() or not full_path_to_delete.is_file():
            messagebox.showerror("Delete File", f"File does not exist: {full_path_to_delete}")
            return

        if not messagebox.askyesno("Delete File", f"Delete {filename}?"):
            return

        try:
            os.remove(full_path_to_delete)
            # Stage deletion
            try:
                add_result = self.repo.add(repo_rel)
                # repo.add may return success info; ignore if not present
            except Exception:
                pass
            # remove editor if open
            str_full = str(full_path_to_delete)
            if str_full in self.file_editors:
                try:
                    self.file_editors[str_full].destroy()
                except Exception:
                    pass
                del self.file_editors[str_full]
            if self.current_file_path == str_full:
                self.current_file_path = None
                self.active_editor = None
            messagebox.showinfo("Deleted", f"File deleted and staged: {filename}")
        except Exception as e:
            messagebox.showerror("Error", str(e))
        finally:
            self.refresh_files()

    def create_file(self, folder_path):
        """
        Prompt for a new file name, create it on disk, stage it and refresh.
        folder_path is a Path object pointing at the folder in the repo.
        """
        if not folder_path.exists() or not folder_path.is_dir():
            messagebox.showerror("Error", f"Folder does not exist: {folder_path}")
            return

        name = simpledialog.askstring("New File", "Enter new file name:")
        if not name:
            return

        new_file = folder_path / name
        if new_file.exists():
            messagebox.showerror("Error", "File already exists.")
            return

        try:
            new_file.touch()
            # Stage the new file
            try:
                rel_for_add = str(new_file.relative_to(self.repo.working_dir))
            except Exception:
                rel_for_add = str(new_file.relative_to(self.repo_path))
            try:
                self.repo.add(rel_for_add)
            except Exception:
                pass
            messagebox.showinfo("Created", f"File created and staged: {new_file.name}")
        except Exception as e:
            messagebox.showerror("Error", str(e))
        finally:
            self.refresh_files()

    def delete_folder(self, folder_path):
        """
        Delete a folder and its contents, stage the deletion, refresh.
        """
        if not folder_path.exists() or not folder_path.is_dir():
            messagebox.showerror("Error", f"Folder does not exist: {folder_path}")
            return

        if not messagebox.askyesno("Delete Folder", f"Delete folder {folder_path.name} and all contents?"):
            return

        try:
            import shutil
            shutil.rmtree(folder_path)
            try:
                rel_for_add = str(folder_path.relative_to(self.repo.working_dir))
            except Exception:
                rel_for_add = str(folder_path.relative_to(self.repo_path))
            try:
                self.repo.add(rel_for_add)
            except Exception:
                pass
            messagebox.showinfo("Deleted", f"Folder deleted and staged: {folder_path.name}")
        except Exception as e:
            messagebox.showerror("Error", str(e))
        finally:
            self.refresh_files()

    def commit_action(self):
        if not self.current_file_path:
            messagebox.showinfo("Commit", "No file selected.")
            return

        self.save_current_file()

        # Use current_file_path relative to repo
        try:
            rel_path = str(Path(self.current_file_path).relative_to(self.repo_path))
        except Exception:
            rel_path = str(Path(self.current_file_path).name)

        add_result = self.repo.add(rel_path)
        if not add_result.get("success", True):
            messagebox.showerror("Add Error", add_result.get("message", "Failed to add file"))
            return

        msg = simpledialog.askstring("Commit", "Enter commit message:")
        if not msg:
            return

        commit_result = self.repo.commit(msg)
        if commit_result.get("success", False):
            messagebox.showinfo("Commit", commit_result.get("message", "Committed"))
        else:
            messagebox.showerror("Commit", commit_result.get("message", "Commit failed"))

    def history_action(self):
        """
        Show the commit history for the current branch.
        """
        try:
            current_branch = self.repo.current_branch()
            commits = self.repo.list_commits(current_branch)
        except Exception as e:
            messagebox.showerror("History Error", str(e))
            return

        if not commits:
            messagebox.showinfo("History", "No commits yet")
            return

        text = "\n".join([f"{c['oid'][:8]} — {c.get('message','')}" for c in commits])
        messagebox.showinfo("Version History", text)

    def rollback_action(self):
        """
        Show a dialog to pick a commit to rollback to. Calls repo.restore_commit(oid).
        """
        try:
            branch = self.repo.current_branch()
            commits_data = self.repo.list_commits(branch)
        except Exception as e:
            messagebox.showerror("Rollback Error", str(e))
            return

        if not commits_data:
            messagebox.showinfo("Rollback", "No commits available.")
            return

        dialog = tk.Toplevel(self)
        dialog.title("Rollback")
        dialog.geometry("420x260")
        dialog.resizable(False, False)

        tk.Label(dialog, text=f"Rollback - Branch: {branch}", font=("Segoe UI", 10, "bold")).pack(pady=10)
        tk.Label(dialog, text="Select a commit:", anchor="w").pack(fill="x", padx=10)

        commit_var = tk.StringVar()
        commit_dropdown = ttk.Combobox(dialog, textvariable=commit_var, state="readonly")

        display_list = []
        commit_map = {}

        for commit_obj in commits_data:
            oid = commit_obj["oid"]
            msg = commit_obj.get("message", "")
            display = f"{oid[:8]}  |  {msg}"
            display_list.append(display)
            commit_map[display] = oid

        commit_dropdown["values"] = display_list
        if display_list:
            commit_dropdown.current(0)
        commit_dropdown.pack(fill="x", padx=10, pady=5)

        def apply_rollback():
            display = commit_var.get()
            oid = commit_map.get(display)
            if not oid:
                messagebox.showerror("Error", "Invalid commit selected.")
                return

            try:
                restore_result = self.repo.restore_commit(oid)
            except Exception as e:
                messagebox.showerror("Rollback", str(e))
                return

            if restore_result.get("success", False):
                messagebox.showinfo("Rollback", restore_result.get("message", "Rollback applied"))
                self.refresh_files()
                dialog.destroy()
            else:
                messagebox.showerror("Rollback", restore_result.get("message", "Rollback failed"))

        tk.Button(dialog, text="Apply", command=apply_rollback).pack(side="right", padx=10, pady=15)
        tk.Button(dialog, text="Cancel", command=dialog.destroy).pack(side="right", pady=15)

    def branch_action(self):
        name = simpledialog.askstring("Branch", "New branch name:")
        if not name:
            return

        try:
            branch_result = self.repo.create_branch(name)
        except Exception as e:
            messagebox.showerror("Branch Error", str(e))
            return

        if branch_result.get("success", False):
            messagebox.showinfo("Branch", branch_result.get("message", "Branch created"))
        else:
            messagebox.showerror("Branch", branch_result.get("message", "Failed to create branch"))

    def switch_branch_action(self):
        branches = self.repo.list_branches()
        if not branches:
            messagebox.showinfo("Branches", "No branches available.")
            return
        name = simpledialog.askstring("Switch Branch", f"Available:\n{', '.join(branches)}")
        if not name:
            return

        res = self.repo.switch_branch(name)
        if res.get("success", False):
            messagebox.showinfo("Switch", res.get("message", "Switched branch"))
            # IMPORTANT: This clears the old file editors so undo history
            # from Branch A doesn't bleed into Branch B
            self.refresh_files()
        else:
            messagebox.showerror("Error", res.get("message", "Switch failed"))

    def merge_action(self):
        branches = self.repo.list_branches()
        if not branches:
            messagebox.showinfo("Merge", "No branches found")
            return

        current_branch = self.repo.current_branch()
        name = simpledialog.askstring("Merge", f"Merge branch into {current_branch}:\n{', '.join(branches)}")
        if not name:
            return

        try:
            merge_result = self.repo.merge_branch(name)
        except Exception as e:
            messagebox.showerror("Merge Error", str(e))
            return
        
        self.refresh_files()

        if not merge_result.get("success", False):
            if merge_result.get("conflicts"):
                response = messagebox.askyesno("Merge Conflict",
                                               f"Automatic merge produced conflicts in directory: {merge_result.get('merge_dir','unknown')}.\n"
                                               f"Do you want to open the repository folder to resolve conflicts manually?")
                if response:
                    # Open the repo working directory in file explorer as a convenience (best-effort)
                    try:
                        import subprocess, platform
                        wd = str(self.repo.working_dir)
                        if platform.system() == "Windows":
                            subprocess.Popen(["explorer", wd])
                        elif platform.system() == "Darwin":
                            subprocess.Popen(["open", wd])
                        else:
                            subprocess.Popen(["xdg-open", wd])
                    except Exception:
                        pass
                    messagebox.showinfo("Merge", "Please resolve conflicts manually and then commit.")
                else:
                    messagebox.showinfo("Merged Forcefully", "Resolve conflicts manually.")
            else:
                messagebox.showerror("Merge", merge_result.get("message", "Merge failed"))
            return

        messagebox.showinfo("Merge", merge_result.get("message", "Merge successful"))
        self.refresh_files()


# -------------------------------
# Main Application
# -------------------------------
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Gible VCS")

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        
        # Get the screen dimensions dynamically
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()

        # Set the window geometry to full screen
        # self.overrideredirect(False)
        
        self.geometry(f"{screen_width}x{screen_height}+0+0")
        
        self.iconbitmap("images/gible_w.ico")

        self.bind("<Escape>", lambda e: self.destroy())

        self.frames = {}
        for F in (RepoListScreen, ExplorerEditorScreen):
            frame = F(self)
            self.frames[F] = frame
            frame.grid(row=0, column=0, sticky="nsew")

        self.show_frame(RepoListScreen)

    def show_frame(self, cls):
        self.frames[cls].tkraise()

    def show_frame_with_repo(self, cls, repo_data):
        frame = self.frames[cls]
        frame.load_repo(repo_data)
        frame.tkraise()


# -------------------------------
# Run
# -------------------------------
if __name__ == "__main__":
    app = App()
    app.mainloop()
