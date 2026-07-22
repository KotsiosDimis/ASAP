import os
import sys
import time
import threading
import argparse
import traceback
import queue
import fcntl

try:
    import select
    import termios
    import tty
except ImportError:  # pragma: no cover - defensive for non-standard terminals
    select = None
    termios = None
    tty = None

import app
import jobs


def run_monitor(target, silent, name, error_queue, stop_event):
    try:
        target(silent, stop_event)
    except Exception:
        exc = traceback.format_exc()
        if not silent:
            print(f"Error in monitor '{name}':")
            print(exc)
        error_queue.put((name, exc))
        stop_event.set()


def escape_watcher(stop_event):
    if select is None or termios is None or tty is None:
        return

    tty_fd = None
    fd = None
    try:
        if sys.stdin.isatty():
            fd = sys.stdin.fileno()
        else:
            try:
                tty_fd = os.open('/dev/tty', os.O_RDONLY | os.O_NONBLOCK)
                fd = tty_fd
            except OSError:
                return

        old_settings = termios.tcgetattr(fd)
        old_flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        tty.setcbreak(fd)
        fcntl.fcntl(fd, fcntl.F_SETFL, old_flags | os.O_NONBLOCK)

        while not stop_event.is_set():
            try:
                ch = os.read(fd, 1)
            except BlockingIOError:
                ch = b''
            except OSError:
                break
            if ch == b"\x1b":
                stop_event.set()
                break
            time.sleep(0.05)
    finally:
        if fd is not None:
            try:
                fcntl.fcntl(fd, fcntl.F_SETFL, old_flags)
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            except Exception:
                pass
        if tty_fd is not None:
            os.close(tty_fd)


def start_escape_watcher(stop_event):
    watcher = threading.Thread(target=escape_watcher, args=(stop_event,), daemon=True, name="escape-watcher")
    watcher.start()
    return watcher


def main(silent=False, run_app=True, run_jobs=True):
    error_queue = queue.Queue()
    stop_event = threading.Event()
    threads = []

    if run_app:
        threads.append(threading.Thread(target=run_monitor, args=(app.main, silent, "app", error_queue, stop_event), name="app", daemon=True))
    if run_jobs:
        threads.append(threading.Thread(target=run_monitor, args=(jobs.main, silent, "jobs", error_queue, stop_event), name="jobs", daemon=True))

    if not threads:
        raise ValueError("No monitor selected. Use --app, --jobs, or neither to run both.")

    for thread in threads:
        thread.start()

    start_escape_watcher(stop_event)

    try:
        while any(thread.is_alive() for thread in threads) and not stop_event.is_set():
            try:
                name, exc = error_queue.get_nowait()
            except queue.Empty:
                pass
            else:
                if not silent:
                    print(f"\nMonitor '{name}' failed with an error:")
                    print(exc)
                stop_event.set()
                break

            time.sleep(0.1)
    except KeyboardInterrupt:
        if not silent:
            print("\nKeyboardInterrupt received. Shutting down ASAP monitor...")
        stop_event.set()

    for thread in threads:
        thread.join(timeout=2)

    sys.exit("ASAP monitor stopped by user")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ASAP monitor runner")
    parser.add_argument("--ns", action="store_true", help="No-screen: suppress terminal output; still send notifications")
    parser.add_argument("--app", action="store_true", help="Run only the app monitor")
    parser.add_argument("--jobs", action="store_true", help="Run only the jobs monitor")
    args = parser.parse_args()

    run_app = args.app or not args.jobs
    run_jobs = args.jobs or not args.app

    main(silent=args.ns, run_app=run_app, run_jobs=run_jobs)
