![Project Gible Banner](images/gible-banner-transparent.png)
# Gible VCS
### A Lightweight Offline Version Control System

Gible is a simple, lightweight, offline version control system with a graphical user interface. It is built for individuals or small projects that need basic versioning capabilities—such as saving file states, committing project-wide changes, and rolling back to previous versions—without the complexity of distributed systems like Git.

The application is built entirely in Python, using the **CustomTkinter** library for the UI and standard libraries for file operations.

## Features

*   **Repository Management**

*   **File & Folder Operations**

*   **File Versioning (Snapshots)**

*   **Repository Versioning (Commits)**

## Prerequisites

*   Python 3.8 or newer
*   `pip` (Python's package installer)

## How to Run

Follow these steps to set up and run the application on your local machine.

**1. Clone the Repository**
```bash
git clone https://github.com/Abhinerd/Gible.git
```

**2. Create and Activate a Virtual Environment**

It is highly recommended to use a virtual environment to manage project dependencies.

*   **On macOS / Linux:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```
*   **On Windows:**
    ```bash
    python -m venv venv
    .\venv\Scripts\activate
    ```

**3. Install Dependencies**

The project includes a `requirements.txt` file that lists all necessary Python libraries.

```bash
pip install -r requirements.txt
```

**4. Ensure UI Assets are Present**

Make sure the following icon files are present in the images directory of the project:
*   `folder.png`
*   `file.png`

**5. Run the Application**

Once the dependencies are installed, you can start the application by running the `main.py` script.

```bash
python main.py
```
