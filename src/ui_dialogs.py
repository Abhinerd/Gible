import customtkinter as ctk

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