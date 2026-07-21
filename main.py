"""
ASAP - AS400 Status Alert Platform
-----------------------------------
Runs both monitors at once, each in its own background thread:

  - app.main()  - polls the external systems API, shows a live console
    dashboard, and alerts to Teams on up/down changes.
  - jobs.main() - polls IBM i object metadata and alerts to Teams when
    watched objects appear.

Run with: python3 main.py
Each file can still be run on its own too, e.g. python3 jobs.py.
"""

import sys
import time
import threading
import argparse
import traceback
import queue

import app
import jobs


def run_monitor(target, silent, name, error_queue):
    try:
        target(silent)
    except Exception:
        exc = traceback.format_exc()
        if not silent:
            print(f"Error in monitor '{name}':")
            print(exc)
        error_queue.put((name, exc))


def main(silent=False):
    error_queue = queue.Queue()
    threads = [
        threading.Thread(target=run_monitor, args=(app.main, silent, "app", error_queue), name="app", daemon=False),
        threading.Thread(target=run_monitor, args=(jobs.main, silent, "jobs", error_queue), name="jobs", daemon=False),
    ]

    for thread in threads:
        thread.start()

    try:
        while any(thread.is_alive() for thread in threads):
            try:
                name, exc = error_queue.get_nowait()
            except queue.Empty:
                pass
            else:
                if not silent:
                    print(f"\nMonitor '{name}' failed with an error:")
                    print(exc)
                break
            time.sleep(1)
    except KeyboardInterrupt:
        if not silent:
            print("\nShutting down ASAP monitor...")
        sys.exit("ASAP monitor stopped by user")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ASAP monitor runner")
    parser.add_argument("--ns", action="store_true", help="No-screen: suppress terminal output; still send notifications")
    args = parser.parse_args()
    main(silent=args.ns)
