import os
import json
import time
import requests
from pathlib import Path

# --- Configuration ---
BASE_DIR = Path("/var/silentdoorbell")
SETTINGS_FILE = BASE_DIR / "settings.txt"

# Updated: Define a base URL to make endpoint construction easier
API_BASE_URL = "http://192.168.68.114/api/devices"

# Updated: URLs now reflect the new API structure
SETUP_URL = f"{API_BASE_URL}/setup"
HEARTBEAT_INTERVAL = 180  # 3 minutes
RETRY_INTERVAL = 60       # 1 minute

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json", # Good practice to include Accept header
}

# --- Helper Functions ---
def load_settings():
    """Loads settings from the settings file, or returns defaults."""
    if not SETTINGS_FILE.exists():
        return {"device_type": "1", "version": "0.1"}
    try:
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"⚠️ Could not read settings file, using defaults. Error: {e}")
        return {"device_type": "1", "version": "0.1"}

def save_settings(data):
    """Saves the given data to the settings file."""
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except IOError as e:
        print(f"❌ Critical error: Could not write to settings file. Error: {e}")

# --- API Communication ---
def setup_device():
    """
    Ensures the device has a serial number, requesting one from the server if needed.
    """
    settings = load_settings()
    if "serial_number" in settings:
        print(f"✅ Device already configured with serial: {settings['serial_number']}")
        return settings

    print("🔧 Device not configured. Requesting new serial number...")
    payload = {
        "device_type": settings.get("device_type", "1"),
        "version": settings.get("version", "0.1")
    }
    print("🔄 Setup payload:", json.dumps(payload, indent=2))

    while True:
        try:
            response = requests.post(SETUP_URL, json=payload, headers=HEADERS, timeout=10)
            print(f"🌐 Setup Response: {response.status_code}")
            response.raise_for_status() # Raises an exception for 4xx/5xx errors

            data = response.json()
            serial = data.get("serial_number")
            if serial:
                print(f"✅ Received serial_number: {serial}")
                settings["serial_number"] = serial
                save_settings(settings)
                return settings
            else:
                print("⚠️ No serial_number in response. Retrying in 60s...")

        except requests.exceptions.RequestException as e:
            print(f"❌ Network error during setup: {e}")
        except Exception as e:
            print(f"❌ An unexpected error occurred during setup: {e}")

        time.sleep(RETRY_INTERVAL)

def send_heartbeat(serial_number):
    """Sends a heartbeat to the server to indicate the device is online."""
    # Updated: The URL is now dynamic and includes the serial number.
    heartbeat_url = f"{API_BASE_URL}/{serial_number}/heartbeat"
    print(f"💓 Sending heartbeat to: {heartbeat_url}")

    try:
        # Updated: The payload is now empty as the serial is in the URL.
        response = requests.post(heartbeat_url, headers=HEADERS, timeout=10)
        print(f"🌐 Heartbeat Response: {response.status_code}")
        response.raise_for_status()
        print("✅ Heartbeat sent successfully.")
    except requests.exceptions.RequestException as e:
        print(f"❌ Network error during heartbeat: {e}")
    except Exception as e:
        print(f"❌ An unexpected error occurred during heartbeat: {e}")

def send_ring(serial_number):
    """Sends a doorbell ring event to the server."""
    # New Function: Handles the ring event.
    ring_url = f"{API_BASE_URL}/{serial_number}/ring"
    print(f"🔔 Sending ring event to: {ring_url}")

    try:
        response = requests.post(ring_url, headers=HEADERS, timeout=10)
        print(f"🌐 Ring Response: {response.status_code}")
        response.raise_for_status()
        print("✅ Ring event sent successfully.")
    except requests.exceptions.RequestException as e:
        print(f"❌ Network error during ring event: {e}")
    except Exception as e:
        print(f"❌ An unexpected error occurred during ring event: {e}")


# --- Main Execution ---
if __name__ == "__main__":
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    settings = setup_device()
    serial = settings["serial_number"]


    while True:
        send_heartbeat(serial)
        print(f"--- Waiting for {HEARTBEAT_INTERVAL} seconds... ---")
        time.sleep(HEARTBEAT_INTERVAL)
