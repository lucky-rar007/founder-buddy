"""
Founder Buddy — Main Entry Point.

Launches the FastAPI web server to run the application through the web dashboard.
Includes automatic dependency verification to ensure requirements are met before startup.
"""

import sys
import os
import subprocess
import importlib.util
from pathlib import Path

# Add workspace directory to python path
workspace_path = Path(__file__).resolve().parent
if str(workspace_path) not in sys.path:
    sys.path.insert(0, str(workspace_path))

import shared.logging_config


REQUIRED_PACKAGES = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "dotenv": "python-dotenv",
    "pydantic": "pydantic",
    "requests": "requests",
    "google.generativeai": "google-generativeai",
    "chromadb": "chromadb",
    "onnxruntime": "onnxruntime",
    "apscheduler": "apscheduler",
    "bs4": "beautifulsoup4",
    "cryptography": "cryptography",
    "pytz": "pytz",
    "markdownify": "markdownify",
    "websockets": "websockets"
}


def ensure_requirements_installed() -> None:
    """
    Checks if all required Python packages are installed in the current environment.
    If any package is missing, automatically installs them from requirements.txt.
    """
    missing = []
    for module_name, package_name in REQUIRED_PACKAGES.items():
        if importlib.util.find_spec(module_name) is None:
            missing.append(package_name)

    if missing:
        print(f"\n[Dependency Manager] Missing required packages detected: {', '.join(missing)}")
        req_file = workspace_path / "requirements.txt"
        if req_file.exists():
            print(f"[Dependency Manager] Auto-installing dependencies from requirements.txt...")
            try:
                subprocess.check_call([
                    sys.executable, "-m", "pip", "install", "-r", str(req_file)
                ])
                print("[Dependency Manager] All requirements successfully installed!\n")
            except subprocess.CalledProcessError as e:
                print(f"[Dependency Manager Error] Automatic package installation failed: {e}")
                print("Please run: pip install -r requirements.txt manually.\n")
        else:
            print("[Dependency Manager Warning] requirements.txt not found in workspace root.\n")
    else:
        print("[Dependency Manager] All required packages are installed and verified.")


def start_server(host: str = "127.0.0.1", port: int = 8080, reload: bool = False) -> None:
    """Launch the FastAPI server hosting the web dashboard via Uvicorn."""
    import uvicorn

    print(f"\n{'=' * 60}")
    print(f"  FOUNDER BUDDY v2.0")
    print(f"  Dashboard: http://{host}:{port}/")
    print(f"  Health:    http://{host}:{port}/health")
    print(f"  API Docs:  http://{host}:{port}/docs")
    print(f"{'=' * 60}")
    print(f"  Press Ctrl+C to stop the server.\n")

    uvicorn.run(
        "server.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
        access_log=True,
    )


def wipe_all_data() -> None:
    """Wipes all local SQLite databases, encryption keys, Chroma vector stores, and raw message files for a fresh setup."""
    import shutil
    data_dir = workspace_path / "data"
    for name in ["founder_buddy.db", "founder_buddy.db-wal", "founder_buddy.db-shm", ".encryption_key"]:
        f = data_dir / name
        if f.exists():
            try:
                os.remove(f)
            except Exception:
                pass
    for dir_name in ["chroma_db", "raw_teams_messages", "raw_outlook_messages"]:
        d = data_dir / dir_name
        if d.exists():
            try:
                shutil.rmtree(d)
            except Exception:
                pass
    env_file = workspace_path / ".env"
    if env_file.exists():
        try:
            os.remove(env_file)
        except Exception:
            pass
    print("\n[Clean Slate] All previous credentials, databases, vector stores, and logs deleted!\n")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Founder Buddy Dashboard Server")
    parser.add_argument(
        "--host", default="127.0.0.1", help="Server host (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=8080, help="Server port (default: 8080)"
    )
    parser.add_argument(
        "--reload", action="store_true", help="Enable auto-reload for development"
    )
    parser.add_argument(
        "--clean", action="store_true", help="Clean slate wipe of all databases, credentials, and message logs before starting"
    )

    args = parser.parse_args()

    if args.clean:
        wipe_all_data()

    # Step 1: Verify & Auto-install missing requirements if needed
    ensure_requirements_installed()

    # Step 2: Start the web server / dashboard
    # HOST and PORT env vars allow Docker/Render deployments without changing CLI args
    host = os.environ.get("HOST", args.host)
    port = int(os.environ.get("PORT", args.port))
    start_server(host=host, port=port, reload=args.reload)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting application gracefully...")
        sys.exit(0)
