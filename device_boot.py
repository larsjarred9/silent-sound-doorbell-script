import os
import json
import time
import requests
from pathlib import Path

BASE_DIR = Path.home() / "silentdoorbell"
SETTINGS_FILE = BASE_DIR / "settings.txt"

SETUP_URL = "https://speetjens.speetjens/device/setup/"
HEARTBEAT_INTERVAL = 180  # 3 minutes
RETRY_INTERVAL = 60       # 1 minute

def load_settings():
    if not SETTINGS_FILE.exists():
        return {"type": "prototype", "version": "0.1"}
    with open(SETTINGS_FILE, "r") as f:
        return json.load(f)

def save_settings(data):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f)

def setup_device():
    settings = load_settings()
    if "serial_number" in settings:
        return settings["serial_number"]

    print("Requesting serial number...")
    while True:
        try:
            response = requests.post(SETUP_URL, json={
                "type": settings.get("type", "prototype"),
                "version": settings.get("version", "0.1")
            }, timeout=10)
            response.raise_for_status()

            data = response.json()
            serial = data.get("serial_number")
            if serial:
                print(f"Received serial_number: {serial}")
                settings["serial_number"] = serial
                save_settings(settings)
                return serial
            else:
                print("No serial_number in response. Retrying in 60s...")
        except Exception as e:
            print(f"Error during setup: {e}")

        time.sleep(RETRY_INTERVAL)

def send_heartbeat(serial_number):
    url = f"https://speetjens.speetjens/device/{serial_number}"
    try:
        print(f"Sending heartbeat to {url}")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        print("Heartbeat sent successfully.")
    except Exception as e:
        print(f"Heartbeat failed: {e}")

if __name__ == "__main__":
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    serial = setup_device()
    while True:
        send_heartbeat(serial)
        time.sleep(HEARTBEAT_INTERVAL)
