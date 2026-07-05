import sys
from pathlib import Path

# Add workspace directory to python path
workspace_path = Path(__file__).resolve().parent
if str(workspace_path) not in sys.path:
    sys.path.append(str(workspace_path))

from apps.jobs.ingestor import run_manual, run_scheduler_daemon, configure_schedule

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Founder Buddy Main Entrypoint")
    parser.add_argument(
        "mode",
        choices=["manual", "schedule", "configure-schedule"],
        nargs="?",
        default=None,
        help="Running mode (manual, schedule, or configure-schedule)"
    )
    
    args = parser.parse_args()
    
    if args.mode is None:
        # Provide an interactive menu if no mode is specified
        print("=== Founder Buddy CLI ===")
        print("  [1] Run Manual Ingestion")
        print("  [2] Configure Scheduler")
        print("  [3] Run Scheduler Daemon")
        print("  [4] Exit")
        choice = input("Select an option (1-4): ").strip()
        if choice == "1":
            run_manual()
        elif choice == "2":
            configure_schedule()
        elif choice == "3":
            run_scheduler_daemon()
        else:
            print("Exiting.")
    elif args.mode == "manual":
        run_manual()
    elif args.mode == "configure-schedule":
        configure_schedule()
    elif args.mode == "schedule":
        run_scheduler_daemon()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting application gracefully...")
        sys.exit(0)
