![Project Gible Banner](images/gible-banner-color.png)

# Gible VCS

**Gible VCS** is a lightweight, custom-built version control system written in Python.  
It provides a simple GUI and CLI for managing repositories, tracking changes, committing files, branching, merging, and exporting/importing repositories.  

Think of it as a minimal Git-like tool, but designed to be approachable, educational, and easy to use.

---

## Features

- **Repository Management**
  - Create, import, export, and delete repositories
  - Persistent storage of tracked repositories in JSON
- **File Explorer + Editor**
  - Browse repository files with a tree view
  - Edit files with syntax-friendly text editor
  - Undo/redo support
- **Version Control**
  - Stage files and commit changes
  - View commit history
  - Rollback to previous commits
  - Branch creation, switching, and merging
  - Proper handling of file deletions
- **Import/Export**
  - Import repositories from `.zip`
  - Export repositories to `.zip`
- **Cross-platform**
  - Works on Windows, macOS, and Linux
  - Prebuilt **Windows executable** available in Releases

---

## Installation

You can use Gible VCS in two ways:

### Option 1: Clone and Run with Python
1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/gible-vcs.git
   cd gible-vcs
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the app:
   ```bash
   python gible.py
   ```

### Option 2: Use the Windows Executable
- Download the latest `.exe` from the [Releases](https://github.com/yourusername/gible-vcs/releases).
- Run `Gible.exe` directly — no Python required.

---

## Usage

1. **Repositories Screen**
   - Add a folder as a repository
   - Import from `.zip`
   - Export to `.zip`
   - Delete or uninitialize repositories

2. **Explorer + Editor**
   - Navigate files in the repository
   - Edit files with undo/redo
   - Save changes with `Ctrl+S` (or `Cmd+S` on macOS)
   - Right-click files/folders for context actions (create, delete, info)

3. **Version Control Actions**
   - **Commit**: Save changes with a message
   - **History**: View commit log
   - **Rollback**: Restore previous commit
   - **Branch**: Create new branches
   - **Switch**: Change active branch
   - **Merge**: Merge branches with conflict handling

---

## Project Structure

```
.
├── README.md
├── requirements.txt
├── images/
└── src/
    ├── base.py
    └── gible.py
```

---

## Development Notes

- Built with **Python 3.10+**
- GUI powered by **CustomTkinter**
- Diff/patch using **bsdiff4** and **difflib**
- Uses JSON for metadata and staging index
- Packaged into `.exe` using **PyInstaller**
