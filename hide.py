import subprocess
import os
import time

def hide_folder(folder_path):
    """Hide a folder in macOS Finder."""
    if os.path.exists(folder_path):
        subprocess.run(["chflags", "hidden", folder_path], check=True)
        print(f"Hidden: {folder_path}")
    else:
        print("Folder not found.")

def unhide_folder(folder_path):
    """Unhide a folder in macOS Finder."""
    if os.path.exists(folder_path):
        subprocess.run(["chflags", "nohidden", folder_path], check=True)
        print(f"Unhidden: {folder_path}")
    else:
        print("Folder not found.")

folder = "/Users/abhinav/Documents/Gible/Repositories"
# time.sleep(5)
# hide_folder(folder)
# time.sleep(5)
# unhide_folder(folder)