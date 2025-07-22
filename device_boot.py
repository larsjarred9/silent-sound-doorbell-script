import os
import json
import time
import requests
from pathlib import Path

BASE_DIR = Path("/var/silentdoorbell")
SETTINGS_FILE = BASE_DIR / "settings.txt"

SETUP_URL = "http://192.168.68.114/api/device/setup/"
HEARTBEAT_URL = "http://192.168.68.114/api/device/heartbeat/"
HEARTBEAT_INTERVAL = 180  # 3 minutes
RETRY_INTERVAL = 60       # 1 minute

HEADERS = {
    "Content-Type": "application/json"
}

def load_settings():
    if not SETTINGS_FILE.exists():
        return {"device_type": "prototype", "version": "0.1"}
    with open(SETTINGS_FILE, "r") as f:
        return json.load(f)

def save_settings(data):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f)

def setup_device():
    settings = load_settings()
    if "serial_number" in settings:
        return settings

    print("🔧 Requesting serial number...")
    payload = {
        "device_type": settings.get("device_type", "prototype"),
        "version": settings.get("version", "0.1")
    }
    print("🔄 Setup payload:", json.dumps(payload, indent=2))

    while True:
        try:
            response = requests.post(
                SETUP_URL,
                json=payload,
                headers=HEADERS,
                timeout=10
            )
            print("🌐 Setup status:", response.status_code)
            print("📩 Response:", response.text)

            response.raise_for_status()
            data = response.json()
            serial = data.get("serial_number")
            if serial:
                print(f"✅ Received serial_number: {serial}")
                settings["serial_number"] = serial
                save_settings(settings)
                return settings
            else:
                print("⚠️ No serial_number in response. Retrying in 60s...")
        except requests.exceptions.HTTPError as e:
            print(f"❌ HTTP error: {e}")
            print("🔍 Server response:", e.response.text)
        except Exception as e:
            print(f"❌ Other error during setup: {e}")

        time.sleep(RETRY_INTERVAL)

def send_heartbeat(serial_number, device_type):
    payload = {
        "serial_number": serial_number,
        "device_type": device_type
    }
    print("💓 Sending heartbeat payload:", json.dumps(payload, indent=2))

    try:
        response = requests.post(
            HEARTBEAT_URL,
            json=payload,
            headers=HEADERS,
            timeout=10
        )
        print("🌐 Heartbeat status:", response.status_code)
        print("📩 Response:", response.text)

        response.raise_for_status()
        print("✅ Heartbeat sent successfully.")
    except requests.exceptions.HTTPError as e:
        print(f"❌ Heartbeat HTTP error: {e}")
        print("🔍 Server response:", e.response.text)
    except Exception as e:
        print(f"❌ Other error during heartbeat: {e}")

if __name__ == "__main__":
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    settings = setup_device()
    serial = settings["serial_number"]
    device_type = settings.get("device_type", "prototype")

    while True:
        send_heartbeat(serial, device_type)
        time.sleep(HEARTBEAT_INTERVAL)
