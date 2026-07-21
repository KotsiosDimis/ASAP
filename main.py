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

import app
import jobs


def main():
    threads = [
        threading.Thread(target=app.main, name="app", daemon=True),
        threading.Thread(target=jobs.main, name="jobs", daemon=True),
    ]

    for thread in threads:
        thread.start()

    try:
        while any(thread.is_alive() for thread in threads):
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down ASAP monitor...")
        sys.exit("ASAP monitor stopped by user")


if __name__ == "__main__":
    main()
