import os
import sys
import subprocess
import venv
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
VENV_DIR = PROJECT_ROOT / ".venv"
REQUIREMENTS_FILE = PROJECT_ROOT / "requirements.txt"
ENV_FILE = PROJECT_ROOT / ".env"
ENV_TEMPLATE = """# WisdomAI MVP Environment Configuration
GOOGLE_GENAI_USE_VERTEXAI=TRUE
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_CLOUD_LOCATION=global
"""

def check_python_version():
    """Ensure Python 3.8+ is being used."""
    if sys.version_info < (3, 8):
        print(f"[-] Error: Python 3.8 or higher is required. Current version: {sys.version}")
        sys.exit(1)

def create_virtual_environment():
    """Create a virtual environment if it doesn't exist."""
    if not VENV_DIR.exists():
        print(f"[*] Creating virtual environment in {VENV_DIR}...")
        venv.create(VENV_DIR, with_pip=True)
        print("[+] Virtual environment created successfully.")
    else:
        print("[*] Virtual environment already exists.")

def get_venv_python():
    """Get the path to the python executable inside the virtual environment."""
    if os.name == "nt":
        return str(VENV_DIR / "Scripts" / "python.exe")
    return str(VENV_DIR / "bin" / "python")

def install_dependencies():
    """Install dependencies from requirements.txt inside the venv."""
    venv_python = get_venv_python()
    print("[*] Upgrading pip inside virtual environment...")
    subprocess.run([venv_python, "-m", "pip", "install", "--upgrade", "pip"], check=True)
    
    if REQUIREMENTS_FILE.exists():
        print(f"[*] Installing dependencies from {REQUIREMENTS_FILE.name}...")
        subprocess.run([venv_python, "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)], check=True)
        print("[+] Dependencies installed successfully.")
    else:
        print(f"[-] Warning: {REQUIREMENTS_FILE.name} not found. Skipping dependency installation.")

def setup_env_file():
    """Ensure .env file exists; create from template if not."""
    if not ENV_FILE.exists():
        print(f"[*] Creating template {ENV_FILE.name}...")
        ENV_FILE.write_text(ENV_TEMPLATE, encoding="utf-8")
        print(f"[!] Created .env with default template. Please edit {ENV_FILE.name} to configure your Google Cloud settings.")
    else:
        print("[*] .env file already exists.")

def run_server():
    """Run the FastAPI server (src/api/main.py) via uvicorn using the venv python."""
    venv_python = get_venv_python()
    print("[*] Starting the server on http://localhost:8000 ...")
    try:
        subprocess.run(
            [
                venv_python, "-m", "uvicorn",
                "src.api.main:app",
                "--reload",
                "--host", "0.0.0.0",
                "--port", "8000",
            ],
            cwd=str(PROJECT_ROOT),
        )
    except KeyboardInterrupt:
        print("\n[*] Server stopped by user.")

def main():
    print("========================================")
    print(" WisdomAI Project Setup & Runner Script")
    print("========================================")
    check_python_version()
    create_virtual_environment()
    install_dependencies()
    setup_env_file()
    print("========================================")
    print("[+] Setup complete!")
    
    response = input("\nWould you like to start the server now? (y/n): ").strip().lower()
    if response in ("y", "yes"):
        run_server()

if __name__ == "__main__":
    main()
