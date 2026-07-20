"""
Local demo runner for jobs.py.

This simulates IBM i Db2 rows and Microsoft Teams delivery so you can test the
jobs.py alert logic without installing ibm_db, connecting to IBM i, or sending a
real webhook.

Run:
    python3 demo_jobs.py
"""

import json
import os
import sys
import types


SNAPSHOTS = [
    [
        {
            "OBJLIB": "APPPRD",
            "OBJNAME": "PAYROLL",
            "OBJTYPE": "*PGM",
            "OBJTEXT": "Payroll batch program",
        }
    ],
    [
        {
            "OBJLIB": "APPPRD",
            "OBJNAME": "PAYROLL",
            "OBJTYPE": "*PGM",
            "OBJTEXT": "Payroll batch program",
        },
        {
            "OBJLIB": "APPPRD",
            "OBJNAME": "INVOICE",
            "OBJTYPE": "*PGM",
            "OBJTEXT": "Invoice batch program",
        },
    ],
    [
        {
            "OBJLIB": "APPPRD",
            "OBJNAME": "INVOICE",
            "OBJTYPE": "*PGM",
            "OBJTEXT": "Invoice batch program",
        },
        {
            "OBJLIB": "APPPRD",
            "OBJNAME": "PAYROLL",
            "OBJTYPE": "*PGM",
            "OBJTEXT": "Payroll batch program",
        },
    ],
]

snapshot_index = 0


class FakeStatement:
    def __init__(self, rows):
        self.rows = rows
        self.index = 0


class FakeResponse:
    status = 202

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return b"accepted"


def fake_connect(database, user, password):
    print(f"Fake Db2 connect: database={database}, user={user}")
    return {"database": database, "user": user}


def fake_exec_immediate(conn, sql):
    global snapshot_index

    rows = SNAPSHOTS[min(snapshot_index, len(SNAPSHOTS) - 1)]
    snapshot_index += 1
    print(f"Fake Db2 query returned {len(rows)} row(s). SQL: {sql}")
    return FakeStatement(rows)


def fake_fetch_assoc(stmt):
    if stmt.index >= len(stmt.rows):
        return False

    row = stmt.rows[stmt.index]
    stmt.index += 1
    return row


def fake_free_stmt(stmt):
    return True


def fake_close(conn):
    print("Fake Db2 close")
    return True


def fake_urlopen(req, context=None, timeout=None):
    payload = json.loads(req.data.decode("utf-8"))
    body = payload["attachments"][0]["content"]["body"]
    print("\nFake Teams alert:")
    for block in body:
        print(block["text"])
    print()
    return FakeResponse()


fake_ibm_db = types.SimpleNamespace(
    connect=fake_connect,
    exec_immediate=fake_exec_immediate,
    fetch_assoc=fake_fetch_assoc,
    free_stmt=fake_free_stmt,
    close=fake_close,
)

sys.modules["ibm_db"] = fake_ibm_db

os.environ.setdefault("WEBHOOK_URL_Processes_Status", "https://example.invalid/webhook")
os.environ.setdefault("DB2USER", "DEMOUSER")
os.environ.setdefault("DB2PWD", "DEMOPASSWORD")
os.environ.setdefault(
    "OBJECT_STATS_SQL",
    "SELECT OBJLIB, OBJNAME, OBJTYPE, OBJTEXT FROM DEMO_OBJECTS",
)

import jobs


jobs.urllib.request.urlopen = fake_urlopen


def run_demo():
    previous_rows = []

    for check_number in range(1, 4):
        print(f"Check {check_number}")
        conn = jobs.getConnection()

        try:
            rows = jobs.fetch_object_rows(conn)
            current_rows = jobs.normalize_rows(rows)
            teams_rows = [row for row in current_rows if row not in previous_rows]

            if teams_rows:
                jobs.send_object_alert(teams_rows)
            else:
                print("No new watched objects. No Teams alert sent.\n")

            previous_rows = current_rows
        finally:
            fake_close(conn)


if __name__ == "__main__":
    run_demo()
