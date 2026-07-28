import json
import ssl
import os
import urllib.request
import urllib.error
import logging
import threading
from datetime import datetime, timezone

try:
    import ibm_db
except ImportError:  # pragma: no cover - allows graceful startup on systems without the package
    ibm_db = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_env(path=None):
    if path is None:
        path = "/home/KDIMITRIOU/projects/final/.env"
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()

# Do not read required env vars at import time — check inside main()
WEBHOOK_URL = None
DB2USER = None
DB2PWD = None

# (equivalent to requests' verify=False)
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Logger for job status history
JOB_LOG_PATH = os.path.join(BASE_DIR, "job_status.log")

job_logger = logging.getLogger("jobs")
job_logger.setLevel(logging.INFO)
job_handler = logging.FileHandler(JOB_LOG_PATH, encoding="utf-8")
job_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
job_logger.addHandler(job_handler)

# Logger for Teams message delivery (own log file so the two monitors don't interleave)
TEAMS_LOG_PATH = os.path.join(BASE_DIR, "job_teams_status.log")

teams_logger = logging.getLogger("jobs_teams")
teams_logger.setLevel(logging.INFO)
teams_handler = logging.FileHandler(TEAMS_LOG_PATH, encoding="utf-8")
teams_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
teams_logger.addHandler(teams_handler)

# Only these program names are relevant for this script.
OBJECT_STATS_SQL = os.getenv("OBJECT_STATS_SQL")

# How often (seconds) the monitor loop re-checks the watched objects.
CHECK_INTERVAL_SECONDS = 30


def set_terminal_message(message, hold_seconds=8):
    try:
        import app
        if hasattr(app, 'set_terminal_message'):
            app.set_terminal_message(message, hold_seconds=hold_seconds)
    except Exception:
        pass


def getConnection():
    if ibm_db is None:
        raise RuntimeError("ibm_db is not installed; IBM i Db2 support is unavailable")
    try:
        return ibm_db.connect("*LOCAL", DB2USER, DB2PWD)
    except Exception as e:
        job_logger.error(f"Unable to connect to Db2: {e}")
        raise


def getData(conn, sqlStr):
    try:
        return ibm_db.exec_immediate(conn, sqlStr)
    except Exception as e:
        job_logger.error(f"Unable to run query: {e}")
        return None


def fetch_object_rows(conn):
    stmt = getData(conn, OBJECT_STATS_SQL)
    if stmt is None:
        return None

    rows = []
    row = ibm_db.fetch_assoc(stmt)
    while row:
        rows.append((
            (row.get("OBJLIB") or "").strip(),
            (row.get("OBJNAME") or "").strip(),
            (row.get("OBJTYPE") or "").strip(),
            (row.get("OBJTEXT") or "").strip(),
        ))
        row = ibm_db.fetch_assoc(stmt)

    ibm_db.free_stmt(stmt)
    return rows


def send_object_alert(rows, silent=True):
    lines = [
        f"{objlib}.{objname} ({objtype}) - {objtext}"
        for objlib, objname, objtype, objtext in rows
    ]
    if rows:
        summary = "\n".join(lines)
        if not silent:
            print(f"Found {len(rows)} watched object(s):")
            print(summary)
    else:
        summary = "No watched objects found."
        if not silent:
            print(summary)

    payload = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "type": "AdaptiveCard",
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": "IBM i - Watched program object metadata",
                            "weight": "Bolder",
                            "size": "Medium",
                            "color": "Attention"
                        },
                        {
                            "type": "TextBlock",
                            "text": summary,
                            "wrap": True
                        },
                        {
                            "type": "TextBlock",
                            "text": f"Checked at (UTC): {datetime.now(timezone.utc)}",
                            "wrap": True,
                            "isSubtle": True
                        }
                    ]
                }
            }
        ]
    }

    if not WEBHOOK_URL:
        teams_logger.error("WEBHOOK_URL not configured; cannot send object metadata alert")
        return

    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=data_bytes,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, context=ssl_context, timeout=10) as response:
            status = response.status
            body = response.read().decode()
            if status in (200, 202):
                teams_logger.info(f"Object metadata alert sent successfully. Status: {status}")
            else:
                teams_logger.error(f"Object metadata alert got unexpected response: {status} - {body}")
    except urllib.error.HTTPError as e:
        teams_logger.error(f"Object metadata alert failed - HTTPError: {e.code} - {e.reason}")
    except urllib.error.URLError as e:
        teams_logger.error(f"Object metadata alert failed - URLError: {e.reason}")
    except Exception as e:
        teams_logger.error(f"Object metadata alert failed - Unexpected error: {e}")


def main(silent=True, stop_event=None):
    global WEBHOOK_URL, DB2USER, DB2PWD, OBJECT_STATS_SQL
    if stop_event is None:
        stop_event = threading.Event()

    # reload env in case .env was changed after import
    load_env()
    WEBHOOK_URL = os.getenv("WEBHOOK_URL_Processes_Status") or os.getenv("WEBHOOK_URL")
    DB2USER = os.getenv("DB2USER")
    DB2PWD = os.getenv("DB2PWD")
    OBJECT_STATS_SQL = os.getenv("OBJECT_STATS_SQL")

    if not WEBHOOK_URL or not DB2USER or not DB2PWD or not OBJECT_STATS_SQL:
        message = "Missing required env vars for jobs monitor: WEBHOOK_URL, DB2USER, DB2PWD and OBJECT_STATS_SQL must be set"
        if not silent:
            print(message)
        job_logger.error(message)
        set_terminal_message(message, hold_seconds=10)
        return

    previous_rows = set()

    while not stop_event.is_set():
        teams_rows = []
        conn = None

        try:
            # A fresh connection + exec_immediate every cycle is the
            # slower but proven-reliable pattern from the original script.
            # A connection/prepared-statement reuse optimization was tried
            # here and caused the monitor to silently stop sending Teams
            # alerts, so it's been reverted in favor of correctness.
            conn = getConnection()
            rows = fetch_object_rows(conn)

            if rows is None:
                error_message = "Failed to fetch object metadata."
                if not silent:
                    print(error_message)
                job_logger.error(error_message)
                set_terminal_message(error_message, hold_seconds=10)
            else:
                # Rows are hashable tuples, so a set diff is O(n) instead of
                # the original's O(n^2) "row not in previous_rows" scan.
                current_rows = set(rows)
                new_rows = current_rows - previous_rows

                if new_rows:
                    for row in new_rows:
                        objlib, objname, objtype, objtext = row
                        if not silent:
                            print(
                                f"New watched object found: "
                                f"{objlib}.{objname} ({objtype}) - {objtext}"
                            )
                        teams_rows.append(row)

                    send_object_alert(teams_rows, silent=silent)
                    job_logger.info(
                        f"Sent Teams alert for {len(teams_rows)} new watched object row(s)."
                    )

                if current_rows != previous_rows:
                    previous_rows = current_rows

        except Exception as e:
            error_message = f"Object monitor check failed: {e}"
            if not silent:
                print(error_message)
            job_logger.error(error_message)
            set_terminal_message(error_message, hold_seconds=10)

        finally:
            if conn is not None:
                try:
                    ibm_db.close(conn)
                except Exception:
                    pass

        if stop_event.wait(CHECK_INTERVAL_SECONDS):
            break

    if not silent:
        print("Jobs monitor stopped.")


if __name__ == "__main__":
    # Default behavior: run silently (no terminal output).
    # Pass --s on the command line to enable console print output.
    import sys
    silent_mode = "--s" not in sys.argv
    try:
        main(silent=silent_mode)
    except KeyboardInterrupt:
        if not silent_mode:
            print("\nJobs monitor interrupted by user, exiting.")