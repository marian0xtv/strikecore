#!/usr/bin/env python3
"""
StrikeCore Twilio Bridge — Make calls via Twilio REST API.

Alternative to Asterisk SIP trunk. Uses Twilio's programmable voice API
to initiate calls. Simpler setup, no SIP trunk needed.

Setup:
    1. Create Twilio account at twilio.com
    2. Get a phone number (Italian: +39 prefix available)
    3. Set credentials:
       echo 'TWILIO_SID=ACxxxx' >> ~/.strikecore/twilio.env
       echo 'TWILIO_TOKEN=xxxx' >> ~/.strikecore/twilio.env
       echo 'TWILIO_FROM=+39xxxxxxxxxx' >> ~/.strikecore/twilio.env

Usage:
    twilio-call +393401234567                    # Call with default message
    twilio-call +393401234567 --tts "Pronto"     # Call with TTS
    twilio-call +393401234567 --record            # Call and record
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

CONFIG_DIR = Path.home() / ".strikecore"
ENV_FILE = CONFIG_DIR / "twilio.env"
LOG_DIR = Path.home() / "strikecore-data" / "ip_logs"


def _load_creds():
    """Load Twilio credentials from env file."""
    creds = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().strip().split("\n"):
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                creds[k.strip()] = v.strip()
    # Also check environment
    creds.setdefault("TWILIO_SID", os.environ.get("TWILIO_SID", ""))
    creds.setdefault("TWILIO_TOKEN", os.environ.get("TWILIO_TOKEN", ""))
    creds.setdefault("TWILIO_FROM", os.environ.get("TWILIO_FROM", ""))
    return creds


def make_call(to_number, tts_message="", record=False, label=""):
    """Initiate a Twilio call."""
    creds = _load_creds()
    if not creds.get("TWILIO_SID") or not creds.get("TWILIO_TOKEN"):
        print("[!] Twilio credentials not configured.")
        print(f"    echo 'TWILIO_SID=ACxxxx' >> {ENV_FILE}")
        print(f"    echo 'TWILIO_TOKEN=xxxx' >> {ENV_FILE}")
        print(f"    echo 'TWILIO_FROM=+39xxxxxxxxxx' >> {ENV_FILE}")
        return None

    try:
        from twilio.rest import Client
    except ImportError:
        print("[!] Twilio SDK not installed. Run: pip3 install twilio")
        return None

    client = Client(creds["TWILIO_SID"], creds["TWILIO_TOKEN"])

    # Build TwiML
    if tts_message:
        twiml = f'<Response><Say language="it-IT">{tts_message}</Say><Pause length="30"/></Response>'
    else:
        # Silent call — just connect and hold (for sniffing the connection)
        twiml = '<Response><Pause length="60"/></Response>'

    call_params = {
        "to": to_number,
        "from_": creds["TWILIO_FROM"],
        "twiml": twiml,
        "timeout": 30,
    }
    if record:
        call_params["record"] = True

    try:
        call = client.calls.create(**call_params)
        print(f"[*] Call initiated: {call.sid}")
        print(f"    To: {to_number}")
        print(f"    From: {creds['TWILIO_FROM']}")
        print(f"    Status: {call.status}")

        # Save call metadata
        call_data = {
            "type": "twilio_call",
            "timestamp": datetime.now().isoformat(),
            "call_sid": call.sid,
            "to": to_number,
            "from": creds["TWILIO_FROM"],
            "status": call.status,
            "label": label,
        }
        label_clean = label or to_number.replace("+", "")
        out_path = LOG_DIR / f"{label_clean}_twilio.json"
        out_path.write_text(json.dumps(call_data, indent=2))

        return call
    except Exception as e:
        print(f"[!] Twilio error: {e}")
        return None


def check_status(call_sid):
    """Check call status."""
    creds = _load_creds()
    from twilio.rest import Client
    client = Client(creds["TWILIO_SID"], creds["TWILIO_TOKEN"])
    call = client.calls(call_sid).fetch()
    print(f"Call {call_sid}: {call.status} | Duration: {call.duration}s")
    return call


def main():
    parser = argparse.ArgumentParser(description="StrikeCore Twilio Bridge")
    parser.add_argument("number", nargs="?", help="Phone number to call (e.g., +393401234567)")
    parser.add_argument("--tts", default="", help="Text-to-speech message")
    parser.add_argument("--record", action="store_true", help="Record the call")
    parser.add_argument("--label", default="", help="Target label")
    parser.add_argument("--status", default="", help="Check call status by SID")

    args = parser.parse_args()

    if args.status:
        check_status(args.status)
    elif args.number:
        make_call(args.number, args.tts, args.record, args.label)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
