import customtkinter as ctk
from tkinter import filedialog, ttk, messagebox, Menu
from PIL import Image, ImageTk
import os
import time
import shutil
from customtkinter import CTkInputDialog

from ui_dialogs import RepoSelectDialog
from vcs_core import VCSEngine

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Lightweight Version Control System"); self.geometry("1024x768")
        self.grid_rowconfigure(0, weight=1); self.grid_columnconfigure(0, weight=1)
        ctk.set_appearance_mode("System"); ctk.set_default_color_theme("blue")
        self.base_repo_path = "/Users/abhinav/Documents/Gible/Repositories"
        
        # State Variables
        self.vcs = None # Will hold the VCSEngine instance
        self.current_repo_path = None
        self.current_display_path = None
        self.currently_editing_file = None
        self.undo_stack = []; self.redo_stack = []

        try:
            self.folder_icon = ImageTk.PhotoImage(Image.open("images/folder.png").resize((20, 20)))
            self.file_icon = ImageTk.PhotoImage(Image.open("images/file.png").resize((20, 20)))
        except FileNotFoundError: self.folder_icon = self.file_icon = None
        
        container = ctk.CTkFrame(self, corner_radius=0); container.pack(side="top", fill="both", expand=True)
        container.grid_rowconfigure(0, weight=1); container.grid_columnconfigure(0, weight=1)
        
        self.frames = {}
        self.welcome_frame = ctk.CTkFrame(container); self.repo_frame = ctk.CTkFrame(container)
        self.commit_view_frame = ctk.CTkFrame(container); self.history_view_frame = ctk.CTkFrame(container)
        self.frames["welcome"] = self.welcome_frame; self.frames["repository"] = self.repo_frame
        self.frames["commit"] = self.commit_view_frame; self.frames["history"] = self.history_view_frame

        for frame in self.frames.values():
            frame.grid(row=0, column=0, sticky="nsew")

        self.populate_welcome_frame()
        self.populate_repo_frame()
        self.show_frame("welcome")
        
        self.bind("<Command-s>", self.shortcut_save); self.bind("<Control-s>", self.shortcut_save)

    def populate_welcome_frame(self):
        self.welcome_label = ctk.CTkLabel(self.welcome_frame, text="Welcome", font=("Arial", 24))
        self.welcome_label.pack(pady=20, padx=20)
        ctk.CTkButton(self.welcome_frame, text="Create New Repository", command=self.create_repository_action).pack(pady=10, padx=20)
        ctk.CTkButton(self.welcome_frame, text="Open Existing Repository", command=self.open_repository_action).pack(pady=10, padx=20)

    def populate_repo_frame(self):
        self.repo_frame.grid_columnconfigure(1, weight=1); self.repo_frame.grid_rowconfigure(0, weight=1)
        left_panel = ctk.CTkFrame(self.repo_frame, width=200, corner_radius=0); left_panel.grid(row=0, column=0, sticky="nsw")
        left_panel.grid_rowconfigure(5, weight=1)
        ctk.CTkLabel(left_panel, text="Actions", font=("Arial", 20)).grid(row=0, column=0, pady=20, padx=20)
        ctk.CTkButton(left_panel, text="Commit Changes", command=self.commit_action).grid(row=1, column=0, pady=10, padx=20, sticky="ew")
        ctk.CTkButton(left_panel, text="View History", command=self.view_history_action).grid(row=2, column=0, pady=10, padx=20, sticky="ew")
        ctk.CTkButton(left_panel, text="Rollback", command=self.rollback_action).grid(row=4, column=0, pady=10, padx=20, sticky="ew")
        ctk.CTkButton(left_panel, text="Close Repository", command=self.close_repository_action).grid(row=6, column=0, pady=10, padx=20, sticky="ew")
        
        right_panel = ctk.CTkFrame(self.repo_frame, corner_radius=0); right_panel.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        right_panel.grid_rowconfigure(0, weight=1); right_panel.grid_columnconfigure(0, weight=1)
        
        self.file_explorer_frame = ctk.CTkFrame(right_panel, corner_radius=0, fg_color="transparent"); self.file_explorer_frame.grid(row=0, column=0, sticky="nsew")
        self.file_explorer_frame.grid_rowconfigure(1, weight=1); self.file_explorer_frame.grid_columnconfigure(0, weight=1)
        nav_bar = ctk.CTkFrame(self.file_explorer_frame, corner_radius=0); nav_bar.grid(row=0, column=0, sticky="new")
        ctk.CTkButton(nav_bar, text="Up", width=50, command=self.navigate_up).pack(side="left", padx=5, pady=5)
        self.path_label = ctk.CTkLabel(nav_bar, text="", anchor="w"); self.path_label.pack(side="left", fill="x", expand=True, padx=5, pady=5)
        ctk.CTkButton(nav_bar, text="Upload Folder", width=100, command=self.upload_folder).pack(side="right", padx=5, pady=5)
        ctk.CTkButton(nav_bar, text="Upload File", width=100, command=self.upload_file).pack(side="right", padx=5, pady=5)
        self.tree = ttk.Treeview(self.file_explorer_frame, show='tree'); self._configure_treeview_style()
        self.tree.grid(row=1, column=0, sticky='nsew')
        
        self.tree.bind('<Button-1>', self.on_tree_select) # Left-click to open
        self.tree.bind("<Button-3>", self.show_context_menu) # Right-click (Windows/Linux)
        self.tree.bind("<Button-2>", self.show_context_menu) # Right-click (macOS Trackpad)
        
        self.context_menu = Menu(self.tree, tearoff=0)
        self.context_menu.add_command(label="Create New File", command=self.create_new_file)
        self.context_menu.add_command(label="Create New Folder", command=self.create_new_folder)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Delete", command=self.delete_selected_item)
        
        self.file_viewer_frame = ctk.CTkFrame(right_panel, corner_radius=0, fg_color="transparent"); self.file_viewer_frame.grid(row=0, column=0, sticky="nsew")
        self.file_viewer_frame.grid_rowconfigure(1, weight=1); self.file_viewer_frame.grid_columnconfigure(0, weight=1)
        button_bar = ctk.CTkFrame(self.file_viewer_frame, corner_radius=0); button_bar.grid(row=0, column=0, sticky="new")
        ctk.CTkButton(button_bar, text="Back to Files", command=self.show_file_explorer).pack(side="left", padx=5, pady=5)
        ctk.CTkButton(button_bar, text="Save File", command=self.save_current_file).pack(side="left", padx=5, pady=5)
        self.undo_button = ctk.CTkButton(button_bar, text="Undo Save", command=self.undo_save, state="disabled"); self.undo_button.pack(side="left", padx=5, pady=5)
        self.redo_button = ctk.CTkButton(button_bar, text="Redo Save", command=self.redo_save, state="disabled"); self.redo_button.pack(side="left", padx=5, pady=5)
        self.textbox = ctk.CTkTextbox(self.file_viewer_frame, corner_radius=0, font=("Courier New", 12), undo=True)
        self.textbox.grid(row=1, column=0, sticky="nsew"); self.textbox.configure(state="disabled")

        self.commit_view_frame.grid_columnconfigure(0, weight=1); self.commit_view_frame.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(self.commit_view_frame, text="Commit Changes", font=("Arial", 24)).grid(row=0, column=0, padx=20, pady=20)
        self.commit_message_box = ctk.CTkTextbox(self.commit_view_frame, font=("Arial", 14), wrap="word")
        self.commit_message_box.grid(row=1, column=0, sticky="nsew", padx=20, pady=0)
        commit_button_frame = ctk.CTkFrame(self.commit_view_frame, fg_color="transparent")
        commit_button_frame.grid(row=2, column=0, pady=10)
        ctk.CTkButton(commit_button_frame, text="Cancel", command=lambda: self.show_frame("repository")).pack(side="left", padx=10)
        ctk.CTkButton(commit_button_frame, text="Commit to Main", command=self._perform_commit).pack(side="left", padx=10)
        
        self.history_view_frame.grid_columnconfigure(0, weight=1); self.history_view_frame.grid_rowconfigure(1, weight=1)
        history_top_frame = ctk.CTkFrame(self.history_view_frame, fg_color="transparent")
        history_top_frame.grid(row=0, column=0, padx=20, pady=20, sticky="ew")
        ctk.CTkLabel(history_top_frame, text="Commit History", font=("Arial", 24)).pack(side="left")
        ctk.CTkButton(history_top_frame, text="Back to Files", command=lambda: self.show_frame("repository")).pack(side="right")
        self.history_scroll_frame = ctk.CTkScrollableFrame(self.history_view_frame)
        self.history_scroll_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=0)

    def populate_treeview(self, path):
        for item in self.tree.get_children(): self.tree.delete(item)
        relative_path = os.path.relpath(path, self.current_repo_path); self.path_label.configure(text=f"./{relative_path}")
        try:
            items = [item for item in sorted(os.listdir(path), key=str.lower) if not item.startswith('.')]
            dirs = [d for d in items if os.path.isdir(os.path.join(path, d))]
            files = [f for f in items if os.path.isfile(os.path.join(path, f))]
            
            for d in dirs:
                self.tree.insert('', 'end', text=f" {d}", image=self.folder_icon, values=("dir", d))
            for f in files:
                self.tree.insert('', 'end', text=f" {f}", image=self.file_icon, values=("file", f))

        except Exception as e: print(f"Error reading directory {path}: {e}")

    def commit_action(self):
        self.commit_message_box.delete("1.0", "end")
        self.show_frame("commit")

    def _perform_commit(self):
        if not self.vcs: return
        commit_message = self.commit_message_box.get("1.0", "end-1c").strip()
        if not commit_message:
            messagebox.showerror("Error", "Commit message cannot be empty."); return
        
        if self.vcs.create_commit(commit_message):
            messagebox.showinfo("Success", "Changes committed successfully.")
            self.show_frame("repository")
        else:
            messagebox.showinfo("Information", "No files with saved changes to commit.")

    def view_history_action(self):
        if not self.vcs: return
        self._populate_history_view()
        self.show_frame("history")

    def _populate_history_view(self):
        for widget in self.history_scroll_frame.winfo_children(): widget.destroy()
        
        commits = self.vcs.get_commit_history()
        if not commits:
            ctk.CTkLabel(self.history_scroll_frame, text="No commits have been made yet.").pack(pady=10); return
            
        for commit_data in commits:
            timestamp = commit_data["timestamp"]
            date_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))
            message = commit_data["message"]
            entry_frame = ctk.CTkFrame(self.history_scroll_frame, border_width=1)
            entry_frame.pack(fill="x", padx=5, pady=5, expand=True)
            entry_frame.grid_columnconfigure(0, weight=1)
            msg_label = ctk.CTkLabel(entry_frame, text=message, wraplength=500, justify="left", font=("Arial", 16))
            msg_label.grid(row=0, column=0, sticky="ew", padx=10, pady=5)
            date_label = ctk.CTkLabel(entry_frame, text=f"Committed on: {date_str}", font=("Arial", 12))
            date_label.grid(row=1, column=0, sticky="w", padx=10, pady=(0, 5))
            rollback_btn = ctk.CTkButton(entry_frame, text="Rollback to this commit", 
                                         command=lambda ts=timestamp: self._perform_rollback(ts))
            rollback_btn.grid(row=0, column=1, rowspan=2, padx=10)
    
    def rollback_action(self):
        self.view_history_action()

    def _perform_rollback(self, target_timestamp):
        if not self.vcs: return
        if not messagebox.askyesno("Confirm Rollback", "This will revert all files... Are you sure?"): return
        try:
            self.vcs.rollback_to_commit(target_timestamp)
            messagebox.showinfo("Success", "Repository has been rolled back.")
            self.populate_treeview(self.current_display_path)
            self.show_frame("repository")
        except Exception as e:
            messagebox.showerror("Error", f"Rollback failed.\n\nError: {e}")
            
    def show_frame(self, frame_name):
        self.frames[frame_name].tkraise()
        
    def shortcut_save(self, event=None):
        if self.currently_editing_file:
            self.save_current_file()
        
    def _configure_treeview_style(self):
        style = ttk.Style(); style.theme_use("default"); mode = ctk.get_appearance_mode()
        if mode == "Dark": bg_color, text_color, selected_color = ("#2b2b2b", "#dce4ee", "#347083")
        else: bg_color, text_color, selected_color = ("#ffffff", "#1f1f1f", "#347083")
        style.configure("Treeview", background=bg_color, foreground=text_color, fieldbackground=bg_color, borderwidth=0, rowheight=30)
        style.map("Treeview", background=[("selected", selected_color)], foreground=[("selected", text_color)])
        
    def show_context_menu(self, event):
        """Identifies what was right-clicked and shows the appropriate context menu."""
        item_id = self.tree.identify_row(event.y)
        
        if item_id:
            # User right-clicked on an item (file or folder)
            self.tree.selection_set(item_id) # Select the item
            item_type = self.tree.item(item_id)['values'][0]
            
            # For either files or folders, "Delete" is a valid option
            self.context_menu.entryconfigure("Delete", state="normal")

            # "Create" options are only logical within a folder, not on a file
            if item_type == "file":
                self.context_menu.entryconfigure("Create New File", state="disabled")
                self.context_menu.entryconfigure("Create New Folder", state="disabled")
            else: # It's a directory
                self.context_menu.entryconfigure("Create New File", state="normal")
                self.context_menu.entryconfigure("Create New Folder", state="normal")
        else:
            # User right-clicked on empty space in the current directory
            self.tree.selection_set() # Deselect any previously selected item
            self.context_menu.entryconfigure("Create New File", state="normal")
            self.context_menu.entryconfigure("Create New Folder", state="normal")
            self.context_menu.entryconfigure("Delete", state="disabled")

        # Display the menu at the cursor's location
        self.context_menu.post(event.x_root, event.y_root)
        
    def create_new_file(self):
        dialog = CTkInputDialog(text="Enter the name for the new file:", title="Create File"); file_name = dialog.get_input()
        if not file_name or not file_name.strip(): return
        new_file_path = os.path.join(self.current_display_path, file_name.strip())
        if os.path.exists(new_file_path): messagebox.showerror("Error", "A file or folder with this name already exists."); return
        try:
            with open(new_file_path, 'w') as f: pass
            self.currently_editing_file = new_file_path; self.save_current_file(initial_save=True)
            self.currently_editing_file = None; self.populate_treeview(self.current_display_path)
        except Exception as e: messagebox.showerror("Error", f"Could not create the file.\n\nError: {e}")
        
    def create_new_folder(self):
        dialog = CTkInputDialog(text="Enter the name for the new folder:", title="Create Folder"); folder_name = dialog.get_input()
        if not folder_name or not folder_name.strip(): return
        new_folder_path = os.path.join(self.current_display_path, folder_name.strip())
        if os.path.exists(new_folder_path): messagebox.showerror("Error", "A file or folder with this name already exists."); return
        try: os.makedirs(new_folder_path); self.populate_treeview(self.current_display_path)
        except Exception as e: messagebox.showerror("Error", f"Could not create the folder.\n\nError: {e}")
        
    def delete_selected_item(self):
        if not self.vcs: return
        selected_id = self.tree.selection()
        if not selected_id: return
        item_text = self.tree.item(selected_id[0])['text'].strip()
        item_path = os.path.join(self.current_display_path, item_text)
        if not messagebox.askyesno("Confirm Deletion", f"Are you sure you want to permanently delete '{item_text}'?"): return
        try:
            history_path = self.vcs._get_file_history_path(item_path) # Use vcs method
            if os.path.isfile(item_path): os.remove(item_path)
            elif os.path.isdir(item_path): shutil.rmtree(item_path)
            if os.path.exists(history_path): shutil.rmtree(history_path)
            self.populate_treeview(self.current_display_path)
        except Exception as e: messagebox.showerror("Error", f"Could not delete the item.\n\nError: {e}")
        
    def upload_file(self):
        if not self.vcs: return
        source_path = filedialog.askopenfilename(title="Select a File to Upload");
        if not source_path: return
        dest_path = os.path.join(self.current_display_path, os.path.basename(source_path))
        if os.path.exists(dest_path):
            if not messagebox.askyesno("Confirm Overwrite", "A file with this name already exists. Overwrite?"): return
        try:
            shutil.copy(source_path, dest_path); self.vcs.create_initial_snapshot(dest_path); self.populate_treeview(self.current_display_path)
        except Exception as e: messagebox.showerror("Error", f"Could not upload the file.\n\nError: {e}")
        
    def upload_folder(self):
        if not self.vcs: return
        source_path = filedialog.askdirectory(title="Select a Folder to Upload");
        if not source_path: return
        dest_path = os.path.join(self.current_display_path, os.path.basename(source_path))
        if os.path.exists(dest_path):
            if not messagebox.askyesno("Confirm Overwrite", "A folder with this name already exists. Overwrite?"): return
            else: shutil.rmtree(dest_path)
        try:
            shutil.copytree(source_path, dest_path)
            for root, _, files in os.walk(dest_path):
                for file_name in files: self.vcs.create_initial_snapshot(os.path.join(root, file_name))
            self.populate_treeview(self.current_display_path)
        except Exception as e: messagebox.showerror("Error", f"Could not upload the folder.\n\nError: {e}")
        
    def save_current_file(self, initial_save=False):
        if not self.vcs or not self.currently_editing_file:
            if not initial_save: messagebox.showwarning("Warning", "No file is open for editing.")
            return

        new_content = "" if initial_save else self.textbox.get("1.0", "end-1c")
        
        snapshot_path = self.vcs.save_snapshot(self.currently_editing_file, new_content, self.undo_stack)
        if snapshot_path:
            try:
                with open(self.currently_editing_file, 'w', encoding='utf-8') as f:
                    f.write(new_content)
            except Exception as e:
                messagebox.showerror("Error", f"Could not write to file on disk.\n\nError: {e}")
                return
            self.undo_stack.append(snapshot_path)
            self.redo_stack = []
            self.update_undo_redo_buttons()
            if not initial_save: messagebox.showinfo("Success", "File saved successfully!")
        elif not initial_save:
            messagebox.showinfo("Information", "No changes to save.")

    def show_file_content(self, file_path):
        self.currently_editing_file = file_path
        self.undo_stack = []; self.redo_stack = []

        history_path = self.vcs._get_file_history_path(file_path)
        if history_path and os.path.exists(history_path):
            self.undo_stack = [os.path.join(history_path, item) for item in sorted(os.listdir(history_path))]
        
        content_to_display = ""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content_to_display = f.read()
        except Exception as e:
            content_to_display = f"Error reading file: {e}"

        self.file_viewer_frame.tkraise()
        self.textbox.configure(state="normal"); self.textbox.delete("1.0", "end")
        
        viewable_extensions = ['.txt', '.md', '.py', '.html', '.css', '.js', '.json', '.xml']
        filename = os.path.basename(file_path).strip().lower()
        print(filename)
        if any(filename.endswith(ext) for ext in viewable_extensions):
            self.textbox.insert("1.0", content_to_display)
        else:
            self.textbox.insert("1.0", "This file type is not editable."); self.textbox.configure(state="disabled")
            self.currently_editing_file = None
        self.update_undo_redo_buttons()
        
    def undo_save(self):
        if len(self.undo_stack) >= 1 and self.vcs:
            self.redo_stack.append(self.undo_stack.pop())
            content = self.vcs.get_content_from_snapshot(self.undo_stack[-1])
            self.textbox.configure(state="normal"); self.textbox.delete("1.0", "end"); self.textbox.insert("1.0", content)
            self.update_undo_redo_buttons()
            
    def redo_save(self):
        if self.redo_stack and self.vcs:
            self.undo_stack.append(self.redo_stack.pop())
            content = self.vcs.get_content_from_snapshot(self.undo_stack[-1])
            self.textbox.configure(state="normal"); self.textbox.delete("1.0", "end"); self.textbox.insert("1.0", content)
            self.update_undo_redo_buttons()
            
    def update_undo_redo_buttons(self):
        self.undo_button.configure(state="normal" if len(self.undo_stack) > 1 else "disabled")
        self.redo_button.configure(state="normal" if self.redo_stack else "disabled")
        
    def show_file_explorer(self):
        self.currently_editing_file = None; self.undo_stack = []; self.redo_stack = []
        self.textbox.configure(state="disabled")

        selection = self.tree.selection()
        if selection:
            self.tree.selection_remove(selection)

        self.file_explorer_frame.tkraise()
        
    def close_repository_action(self):
        self.show_file_explorer()
        self.current_repo_path = None
        self.vcs = None
        self.title("Lightweight Version Control System")
        self.show_frame("welcome")
        for item in self.tree.get_children(): self.tree.delete(item)
        
    def create_repository_action(self):
        dialog = CTkInputDialog(text="Enter the name for the new repository:", title="Create Repository"); repo_name = dialog.get_input()
        if not repo_name or not repo_name.strip(): return
        try: os.makedirs(self.base_repo_path, exist_ok=True)
        except OSError as e: messagebox.showerror("Error", f"Could not access base directory:\n{self.base_repo_path}\n\nError: {e}"); return
        repo_folder_path = os.path.join(self.base_repo_path, repo_name.strip()); main_folder_path = os.path.join(repo_folder_path, "main")
        if os.path.exists(repo_folder_path): messagebox.showerror("Error", f"A repository named '{repo_name}' already exists.")
        else:
            try: os.makedirs(main_folder_path); self.open_or_create_repo(repo_folder_path)
            except Exception as e: messagebox.showerror("Error", f"Could not create repository folder.\n\nError: {e}")
            
    def open_repository_action(self):
        try:
            if not os.path.isdir(self.base_repo_path): messagebox.showinfo("Information", "Repository directory doesn't exist yet."); return
            repo_list = [d for d in os.listdir(self.base_repo_path) if os.path.isdir(os.path.join(self.base_repo_path, d))]
            if not repo_list: messagebox.showinfo("Information", "No existing repositories found."); return
            dialog = RepoSelectDialog(self, sorted(repo_list)); chosen_repo = dialog.get_selection()
            if chosen_repo: self.open_or_create_repo(os.path.join(self.base_repo_path, chosen_repo))
        except Exception as e: messagebox.showerror("Error", f"An error occurred while finding repositories.\n\nError: {e}")
        
    def open_or_create_repo(self, repo_path):
        self.current_repo_path = repo_path
        self.current_display_path = repo_path
        self.vcs = VCSEngine(repo_path)
        self.title(f"VCS - {os.path.basename(repo_path)}")
        self.populate_treeview(self.current_display_path)
        self.show_frame("repository")
        self.show_file_explorer()
        
    def on_tree_select(self, event):
            """Handles opening a file or folder on a single left-click."""
            item_id = self.tree.identify_row(event.y)
            if not item_id:
                return  # User clicked on empty space, do nothing

            item_values = self.tree.item(item_id)['values']
            item_type = item_values[0]
            real_name = item_values[1]
            selected_path = os.path.join(self.current_display_path, real_name)

            if item_type == "dir":
                self.current_display_path = selected_path
                self.populate_treeview(self.current_display_path)
            else:  # It's a file
                self.show_file_content(selected_path)

    def navigate_up(self):
        if self.current_display_path and self.current_repo_path and self.current_display_path != self.current_repo_path:
            parent_path = os.path.dirname(self.current_display_path)
            self.current_display_path = parent_path
            self.populate_treeview(self.current_display_path)

if __name__ == "__main__":
    app = App()
    app.mainloop()