import json
import ssl
import time
import os
import urllib.request
import urllib.error
import logging

delay = 2.0

#use instead of dotenv package to load environment variables from .env file
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

# NOTE: Do not read required env vars at import time; read them inside `main()` so
# importing this module doesn't abort the whole program when running in mixed
# environments (e.g. when `jobs` monitor lacks Db2 creds).
WEBHOOK_URL = None
API_URL = None


# (equivalent to requests' verify=False)
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# keeps track of last known state per system so we only alert on change
last_state = {}

# Logger for server status history
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATUS_LOG_PATH = os.path.join(BASE_DIR, "status_history.log")

status_logger = logging.getLogger("status")
status_logger.setLevel(logging.INFO)
status_handler = logging.FileHandler(STATUS_LOG_PATH, encoding="utf-8")
status_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
status_logger.addHandler(status_handler)

# Logger for Teams message delivery
TEAMS_LOG_PATH = os.path.join(BASE_DIR, "teams_status.log")

teams_logger = logging.getLogger("teams")
teams_logger.setLevel(logging.INFO)
teams_handler = logging.FileHandler(TEAMS_LOG_PATH, encoding="utf-8")
teams_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
teams_logger.addHandler(teams_handler)



def screen(data, silent=False):
    GREEN = "\033[32m"
    RED = "\033[31m"
    RESET = "\033[0m"
    if silent:
        return

    # Clear the full terminal screen and move cursor to top-left before redrawing.
    print("\033[H\033[2J", end="", flush=True)
    print(f"{'System':<12} {'Online':<8} {'Reason':<20} {'Last Check (UTC)':<30}")
    for item in data:
        system = item['system']
        if item['online']:
            online = f"{GREEN}Yes{RESET}"
        else:
            online = f"{RED}No{RESET}"
        reason = item['reason'] if item['reason'] else "all good"
        last_check = item['dateTimeUtc']
        print(f"{system:<12} {online:<17} {reason:<20} {last_check:<30}", flush=True)
    print("\033[J", end="", flush=True)


def api_call():
    if not API_URL:
        raise RuntimeError("API_URL not configured")

    with urllib.request.urlopen(API_URL, context=ssl_context) as response:
        data = json.loads(response.read().decode())
    return data

def send_teams_initial_status(data):
    lines = [f"{item['system']}: {'Online' if item['online'] else 'Offline'}" for item in data]
    summary = "\n".join(lines)

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
                        {"type": "TextBlock", "text": "Monitoring started - current status:", "weight": "Bolder"},
                        {"type": "TextBlock", "text": summary, "wrap": True}
                    ]
                }
            }
        ]
    }

    if not WEBHOOK_URL:
        teams_logger.error("WEBHOOK_URL not configured; cannot send Teams message")
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
            teams_logger.info(f"Initial status sent successfully. Status: {response.status}")
    except urllib.error.URLError as e:
        teams_logger.error(f"Failed to send initial status: {e}")
    except Exception as e:
        teams_logger.error(f"Unexpected error sending initial status: {e}")

def system_down(system, reason, last_check):
    reason_text = reason if reason else "no reason given"

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
                            "text": f"Alert: {system} is DOWN",
                            "weight": "Bolder",
                            "size": "Medium",
                            "color": "Attention"
                        },
                        {
                            "type": "TextBlock",
                            "text": f"Reason: {reason_text}",
                            "wrap": True
                        },
                        {
                            "type": "TextBlock",
                            "text": f"Last check (UTC): {last_check}",
                            "wrap": True,
                            "isSubtle": True
                        }
                    ]
                }
            }
        ]
    }

   

    if not WEBHOOK_URL:
        teams_logger.error("WEBHOOK_URL not configured; cannot send DOWN alert")
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
                teams_logger.info(f"DOWN alert sent for {system}. Status: {status}")
            else:
                teams_logger.error(f"DOWN alert for {system} got unexpected response: {status} - {body}")
    except urllib.error.HTTPError as e:
        teams_logger.error(f"DOWN alert for {system} failed - HTTPError: {e.code} - {e.reason}")
    except urllib.error.URLError as e:
        teams_logger.error(f"DOWN alert for {system} failed - URLError: {e.reason}")


def system_up(system, reason, last_check):
    reason_text = reason if reason else "no reason given"

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
                            "text": f"{system} is back UP",
                            "weight": "Bolder",
                            "size": "Medium",
                            "color": "Good"
                        },
                        {
                            "type": "TextBlock",
                            "text": f"Reason: {reason_text}",
                            "wrap": True
                        },
                        {
                            "type": "TextBlock",
                            "text": f"Last check (UTC): {last_check}",
                            "wrap": True,
                            "isSubtle": True
                        }
                    ]
                }
            }
        ]
    }

    if not WEBHOOK_URL:
        teams_logger.error("WEBHOOK_URL not configured; cannot send UP alert")
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
                teams_logger.info(f"UP alert sent for {system}. Status: {status}")
            else:
                teams_logger.error(f"UP alert for {system} got unexpected response: {status} - {body}")
    except urllib.error.HTTPError as e:
        teams_logger.error(f"UP alert for {system} failed - HTTPError: {e.code} - {e.reason}")
    except urllib.error.URLError as e:
        teams_logger.error(f"UP alert for {system} failed - URLError: {e.reason}")

def check_and_alert(data):
    for item in data:
        system = item['system']
        online = item['online']
        reason = item['reason']
        last_check = item['dateTimeUtc']

       

        previous = last_state.get(system)



        # only alert the moment a system transitions from online/unknown -> offline
        if not online and previous is not False :
            system_down(system, reason, last_check)
            status_logger.info(f"Alert sent for {system} being DOWN.")

        if online and previous is False:
             system_up(system, reason, last_check)
             status_logger.info(f"Alert sent for {system} being UP.")


        last_state[system] = online
 

def clear_screen(silent=False):
    if silent:
        return
    os.system("cls" if os.name == "nt" else "clear")


def main(silent=False):
    global WEBHOOK_URL, API_URL
    # load env again in case .env was created/modified after import
    load_env()
    WEBHOOK_URL = os.getenv("WEBHOOK_URL_System_Status")
    API_URL = os.getenv("API_URL")

    if not WEBHOOK_URL or not API_URL:
        if not silent:
            print("Missing required env vars for app monitor: WEBHOOK_URL and API_URL must be set")
        teams_logger.error("Missing required env vars for app monitor: WEBHOOK_URL and API_URL must be set")
        return

    clear_screen(silent=silent)
    data = api_call()
    send_teams_initial_status(data)
    while True:
        data = api_call()
        check_and_alert(data)
        screen(data, silent=silent)
        time.sleep(delay)



if __name__ == "__main__":
    main()