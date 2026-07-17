# ASAP — AS400 Status Alert Platform

ASAP monitors the status of in-house and external systems and alerts engineers via 
Microsoft Teams when a system goes up or down. It's designed to run natively on 
IBM i (AS/400).

## Features:

- Polls system status APIs on a schedule
- Detects state changes (up ↔ down)
- Sends real-time alerts to Microsoft Teams
- Runs natively on IBM i / AS400

## Requirements:

`app.py` requires nothing beyond the **Python standard library** — no external packages needed, just Python 3.Python 3.8 or higher — [download here](https://www.python.org/downloads/)

`demo_api.py` is included only for local testing (it simulates the status API so you can try the monitor without a real backend). It requires **Flask**:

```bash
pip install flask
```

You won't need Flask (or `demo_api.py` at all) if you're running against a real API endpoint.

## Setup:

1. Clone the repo
2. Rename `.env.example` to `.env` and fill in your values:
   - `WEBHOOK_URL` — Teams Workflows webhook URL
   - `API_URL` — endpoint returning system status JSON
3. Run: `python app.py`

## Setup with demo_api.py for local testing:

If you don't have a real status API to test against, you can use the included `demo_api.py` to simulate one.

1. Install Flask:
```bash
   pip install flask
```
2. Run the demo API:
```bash
   python demo_api.py
```
3. In your `.env`, set `API_URL` to point to the demo API (e.g. `http://localhost:5000/status`)
4. In a separate terminal, run the monitor:
```bash
   python app.py
```

This lets you see the full alert flow (Teams messages, logs, screen output) without needing a real backend.

## Example alerts

**Monitoring started:**
![Monitoring started](screenshots/initial.png)

**System down alert:**
![Down alert](screenshots/system_down.png)

**System back up alert:**
![Up alert](screenshots/system_up.png)

