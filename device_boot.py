import json
import time
import requests
from pathlib import Path
import threading
import subprocess
import sys

# --- Configuration ---
BASE_DIR = Path("/var/silentdoorbell")
SETTINGS_FILE = BASE_DIR / "settings.txt"
API_BASE_URL = "http://192.168.68.114/api/devices"
HEARTBEAT_INTERVAL = 180  # 3 minutes
RETRY_INTERVAL = 60  # 1 minute
RING_COOLDOWN = 60  # 60 seconds to prevent spamming ring events

# Centralized default settings. This is now the single source of truth for defaults.
DEFAULT_SETTINGS = {
    "device_type_id": 1,
    "version": "0.1"
}

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# --- Global State ---
# Used to prevent spamming the ring event
last_ring_time = 0


# --- Helper Functions ---
def load_or_create_settings():
    """Loads settings from the settings file. If the file doesn't exist, it creates it with the default settings."""
    if not SETTINGS_FILE.exists():
        print(f"⚠️ Settings file not found. Creating a new one at {SETTINGS_FILE}")
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS
    try:
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"❌ Error reading settings file: {e}. Recreating with defaults.")
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS


def save_settings(data):
    """Saves the given data to the settings file."""
    try:
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except IOError as e:
        print(f"❌ CRITICAL ERROR: Could not write to settings file. Error: {e}")


# --- API Communication & Device Logic ---
def setup_device():
    """Ensures the device has a serial number, requesting one from the server if needed."""
    settings = load_or_create_settings()
    if "serial_number" in settings:
        print(f"✅ Device already configured with serial: {settings['serial_number']}")
        return settings

    print("🔧 Device not configured. Requesting new serial number...")
    payload = {
        "device_type": settings["device_type_id"],
        "version": settings["version"]
    }
    print("🔄 Setup payload:", json.dumps(payload, indent=2))

    while True:
        try:
            setup_url = f"{API_BASE_URL}/setup"
            response = requests.post(setup_url, json=payload, headers=HEADERS, timeout=10)
            print(f"🌐 Setup Response: {response.status_code}")
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

        except requests.exceptions.RequestException as e:
            print(f"❌ Network error during setup: {e}")
        except Exception as e:
            print(f"❌ An unexpected error occurred during setup: {e}")

        time.sleep(RETRY_INTERVAL)


def send_heartbeat(serial_number):
    """Sends a heartbeat, updates settings, and checks for software updates."""
    heartbeat_url = f"{API_BASE_URL}/{serial_number}/heartbeat"
    print(f"💓 Sending heartbeat to: {heartbeat_url}")
    try:
        response = requests.post(heartbeat_url, headers=HEADERS, timeout=10)
        print(f"🌐 Heartbeat Response: {response.status_code}")
        response.raise_for_status()
        print("✅ Heartbeat sent successfully.")

        data = response.json()

        # --- Auto-update logic ---
        settings = load_or_create_settings()
        local_version = settings.get("version")
        server_version = data.get("device_type", {}).get("latest_version")

        if server_version and local_version and server_version != local_version:
            print(f"🚀 New version available! Local: {local_version}, Server: {server_version}. Starting update...")
            trigger_update()  # This function will exit the script

        # --- Integration update logic ---
        if "integrations" in data:
            settings["integrations"] = data["integrations"]
            save_settings(settings)
            print("💾 Updated local settings with server integration data.")

    except requests.exceptions.RequestException as e:
        print(f"❌ Network error during heartbeat: {e}")
    except json.JSONDecodeError:
        print("❌ Could not decode JSON from heartbeat response.")


def trigger_update():
    """Executes the update script from GitHub and exits."""
    update_command = "curl -sS https://raw.githubusercontent.com/larsjarred9/silent-sound-doorbell-script/refs/heads/deployer/deployer.sh | sudo bash"
    print(f"🏃 Executing update command: {update_command}")
    try:
        # Using shell=True is necessary for the pipe '|'
        subprocess.run(update_command, shell=True, check=True, text=True, capture_output=True)
        print("✅ Update command executed successfully. The service should restart automatically.")
    except subprocess.CalledProcessError as e:
        print(f"❌ Update script failed with exit code {e.returncode}.")
        print(f"   stdout: {e.stdout}")
        print(f"   stderr: {e.stderr}")
    except Exception as e:
        print(f"❌ An unexpected error occurred during update: {e}")
    finally:
        print("...Exiting script to allow update to complete...")
        sys.exit()


def send_ring(serial_number):
    """Sends a doorbell ring event and controls the HomeWizard switch."""
    global last_ring_time
    current_time = time.time()

    if current_time - last_ring_time < RING_COOLDOWN:
        print("🚫 Ring event ignored due to cooldown.")
        return

    last_ring_time = current_time

    ring_url = f"{API_BASE_URL}/{serial_number}/ring"
    print(f"🔔 Sending ring event to: {ring_url}")
    try:
        requests.post(ring_url, headers=HEADERS, timeout=10).raise_for_status()
        print("✅ Ring event sent to server successfully.")
    except requests.exceptions.RequestException as e:
        print(f"❌ Network error during ring event: {e}")
        return

    settings = load_or_create_settings()
    homewizard_ip = None
    if "integrations" in settings:
        for integration in settings["integrations"]:
            if integration.get("type") == "homewizard_socket":
                homewizard_ip = integration.get("credentials", {}).get("local_ip")
                break

    if not homewizard_ip:
        print("⚠️ HomeWizard IP not found in settings. Cannot control switch.")
        return

    toggle_switch(homewizard_ip, True)
    threading.Timer(60.0, toggle_switch, args=[homewizard_ip, False]).start()


def toggle_switch(ip_address, power_on):
    """Sends a command to a HomeWizard smart switch."""
    state_url = f"http://{ip_address}/api/v1/state"
    payload = {"power_on": power_on}
    action = "ON" if power_on else "OFF"

    print(f"💡 Turning switch at {ip_address} {action}...")
    try:
        requests.put(state_url, json=payload, timeout=5).raise_for_status()
        print(f"✅ Switch successfully turned {action}.")
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to turn switch {action}. Error: {e}")


# --- Main Execution ---
if __name__ == "__main__":
    settings = setup_device()
    serial = settings["serial_number"]

    print("--- Device is running. Waiting for events. ---")
    while True:
        send_heartbeat(serial)
        print(f"--- Waiting for {HEARTBEAT_INTERVAL} seconds... ---")
        time.sleep(HEARTBEAT_INTERVAL)
