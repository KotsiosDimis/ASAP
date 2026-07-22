import json
import ssl
import time
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


def load_env(path=".env"):
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
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
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


def normalize_rows(rows):
    return sorted(
        rows,
        key=lambda row: (
            row["OBJLIB"],
            row["OBJNAME"],
            row["OBJTYPE"],
            row["OBJTEXT"],
        ),
    )


def fetch_object_rows(conn):
    stmt = getData(conn, OBJECT_STATS_SQL)
    if stmt is None:
        return None

    rows = []
    row = ibm_db.fetch_assoc(stmt)
    while row:
        rows.append({
            "OBJLIB": (row.get("OBJLIB") or "").strip(),
            "OBJNAME": (row.get("OBJNAME") or "").strip(),
            "OBJTYPE": (row.get("OBJTYPE") or "").strip(),
            "OBJTEXT": (row.get("OBJTEXT") or "").strip(),
        })
        row = ibm_db.fetch_assoc(stmt)

    ibm_db.free_stmt(stmt)
    return rows


def send_object_alert(rows, silent=False):
    lines = [
        f"{item['OBJLIB']}.{item['OBJNAME']} ({item['OBJTYPE']}) - {item['OBJTEXT']}"
        for item in rows
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


def main(silent=False, stop_event=None):
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

    previous_rows = []

    while not stop_event.is_set():
        teams_rows = []
        conn = None

        try:
            conn = getConnection()
            rows = fetch_object_rows(conn)

            if rows is None:
                error_message = "Failed to fetch object metadata."
                if not silent:
                    print(error_message)
                job_logger.error(error_message)
                set_terminal_message(error_message, hold_seconds=10)
                continue

            current_rows = normalize_rows(rows)

            if current_rows != previous_rows:
                for row in current_rows:
                    if row not in previous_rows:
                        if not silent:
                            print(
                                f"New watched object found: "
                                f"{row['OBJLIB']}.{row['OBJNAME']} "
                                f"({row['OBJTYPE']}) - {row['OBJTEXT']}"
                            )
                        teams_rows.append(row)

                if teams_rows:
                    send_object_alert(teams_rows, silent=silent)
                    job_logger.info(
                        f"Sent Teams alert for {len(teams_rows)} new watched object row(s)."
                    )
                else:
                    job_logger.info("Watched object rows changed, but no new rows were added.")

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

        if stop_event.wait(20):
            break

    print("Jobs monitor stopped.")


if __name__ == "__main__":
    main()
