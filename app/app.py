import json
import os
import threading
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, request
from twilio.rest import Client

load_dotenv()

from agent.agent import run_agent

app = Flask(__name__)

APP_CONFIG_PATHS = [
    Path(__file__).resolve().parent / "app" / "config.json",
    Path(__file__).resolve().parent / "config.json",
]


def load_config() -> dict:
    for path in APP_CONFIG_PATHS:
        if path.exists():
            with open(path) as f:
                return json.load(f)
    raise FileNotFoundError("No app config found")


@app.route("/sms", methods=["POST"])
def sms():
    config = load_config()
    from_number = request.form.get("From", "")
    body = request.form.get("Body", "").strip()

    # Only respond to your own number
    allowed = config.get("allowed_phone")
    if allowed and from_number != allowed:
        return "", 204

    if not body:
        return _twiml("I didn't get a message. Try again.")

    # Acknowledge immediately — Twilio times out after ~15s
    def run_and_reply():
        try:
            answer = run_agent(body)
        except Exception as e:
            answer = f"Something went wrong: {e}"

        client = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])
        client.messages.create(
            body=answer,
            from_=config.get("twilio_phone_number") or os.environ["TWILIO_PHONE_NUMBER"],
            to=from_number,
        )

    threading.Thread(target=run_and_reply, daemon=True).start()

    return _twiml("On it, searching your files...")


def _twiml(message: str) -> Response:
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response><Message>{message}</Message></Response>"""
    return Response(xml, mimetype="text/xml")


if __name__ == "__main__":
    app.run(debug=False, port=8080)
