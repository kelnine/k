"""Delivery for the two daily messages. Default is stdout + a text file;
set TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID to also push to Telegram.
"""

from __future__ import annotations

import json
import os
import urllib.request


def send(text: str, logfile: str = "messages.log") -> None:
    print(text)
    with open(logfile, "a") as f:
        f.write(text + "\n\n" + "=" * 60 + "\n\n")

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat_id:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=json.dumps({"chat_id": chat_id, "text": text}).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req, timeout=10)
        except OSError as exc:  # delivery is best-effort; the log file has it
            print(f"(telegram delivery failed: {exc})")
