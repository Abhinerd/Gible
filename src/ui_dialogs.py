import customtkinter as ctk
from tkinter import filedialog

class SettingsDialog(ctk.CTkToplevel):
    """A custom dialog for viewing and changing the app's settings."""
    def __init__(self, parent, current_workspace):
        super().__init__(parent)

        self.title("Settings")
        self.geometry("500x180")
        self.transient(parent)
        self.grab_set()

        self.new_workspace_path = None

        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_frame.pack(pady=20, padx=20, fill="x")

        self.label = ctk.CTkLabel(self.main_frame, text="Repository Workspace:")
        self.label.pack(anchor="w")

        self.path_frame = ctk.CTkFrame(self.main_frame)
        self.path_frame.pack(fill="x", pady=(5, 15))

        self.workspace_entry = ctk.CTkEntry(self.path_frame, width=300)
        self.workspace_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.workspace_entry.insert(0, current_workspace)
        self.workspace_entry.configure(state="disabled")

        self.change_button = ctk.CTkButton(self.path_frame, text="Change...", command=self._on_change)
        self.change_button.pack(side="left")

        self.close_button = ctk.CTkButton(self, text="Close", command=self.destroy)
        self.close_button.pack(pady=10)

    def _on_change(self):
        """Opens a dialog to select a new workspace and updates the entry."""
        new_path = filedialog.askdirectory(title="Select a New Workspace Folder")
        if new_path:
            self.new_workspace_path = new_path
            self.workspace_entry.configure(state="normal")
            self.workspace_entry.delete(0, "end")
            self.workspace_entry.insert(0, new_path)
            self.workspace_entry.configure(state="disabled")

    def get_new_path(self):
        """Waits for the window to close and returns the newly selected path."""
        self.wait_window()
        return self.new_workspace_path

class RepoSelectDialog(ctk.CTkToplevel):
    """A custom dialog window for selecting a repository from a list."""
    def __init__(self, parent, repo_list):
        super().__init__(parent)

        self.title("Open Repository")
        self.geometry("350x150")
        self.transient(parent)  # Keep this window on top of the main app
        self.grab_set()         # Make the dialog modal

        self.selection = None

        self.label = ctk.CTkLabel(self, text="Select a repository to open:")
        self.label.pack(pady=10, padx=20)

        self.option_menu = ctk.CTkOptionMenu(self, values=repo_list)
        self.option_menu.pack(pady=5, padx=20, fill="x")

        self.open_button = ctk.CTkButton(self, text="Open", command=self._on_open)
        self.open_button.pack(pady=10, side="left", expand=True)

        self.cancel_button = ctk.CTkButton(self, text="Cancel", command=self.destroy)
        self.cancel_button.pack(pady=10, side="right", expand=True)

    def _on_open(self):
        """Sets the selection and closes the dialog."""
        self.selection = self.option_menu.get()
        self.destroy()

    def get_selection(self):
        """Waits for the dialog to be closed and returns the user's selection."""
        self.wait_window()
        return self.selection