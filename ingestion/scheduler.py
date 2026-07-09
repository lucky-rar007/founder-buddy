import sys
from pathlib import Path

# Add workspace directory to python path
workspace_path = Path(__file__).resolve().parent.parent
if str(workspace_path) not in sys.path:
    sys.path.append(str(workspace_path))

from ingestion.ingestor import run_scheduler_daemon

if __name__ == "__main__":
    try:
        run_scheduler_daemon()
    except KeyboardInterrupt:
        print("\nExiting application gracefully...")
        sys.exit(0)
