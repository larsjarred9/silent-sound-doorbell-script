import json
import time
import requests
from pathlib import Path
import threading
import subprocess
import sys
import os

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except (RuntimeError, ImportError):
    print("⚠️ RPi.GPIO library not found or not running on a Pi. GPIO functionality disabled.")
    GPIO_AVAILABLE = False

BASE_DIR = Path("/var/silentdoorbell")
SETTINGS_FILE = BASE_DIR / "settings.txt"
API_BASE_URL = "https://silentdoorbell.edu.speetjens.net/api/devices"
HEARTBEAT_INTERVAL = 180  # 3 minutes
RETRY_INTERVAL = 60  # 1 minute
RING_COOLDOWN = 60  # 60 seconds to prevent spamming ring events
DOORBELL_PIN = 19

DEFAULT_SETTINGS = {
    "device_type_id": 1,
    "version": "0.1"
}

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}

last_ring_time = 0
device_serial_number = None

def load_or_create_settings():
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
    try:
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except IOError as e:
        print(f"❌ CRITICAL ERROR: Could not write to settings file. Error: {e}")

def setup_device():
    settings = load_or_create_settings()
    if "serial_number" in settings:
        print(f"✅ Device already configured with serial: {settings['serial_number']}")
        return settings

    print("🔧 Device not configured. Requesting new serial number...")
    payload = {
        "device_type": settings["device_type_id"],
        "version": settings["version"]
    }

    while True:
        try:
            setup_url = f"{API_BASE_URL}/setup"
            response = requests.post(setup_url, json=payload, headers=HEADERS, timeout=10)
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
    heartbeat_url = f"{API_BASE_URL}/{serial_number}/heartbeat"
    print(f"💓 Sending heartbeat to: {heartbeat_url}")
    try:
        response = requests.post(heartbeat_url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        print("✅ Heartbeat sent successfully.")
        data = response.json()
        settings = load_or_create_settings()
        local_version = settings.get("version")
        server_version = data.get("device_type", {}).get("latest_version")
        if server_version and local_version and server_version != local_version:
            print(f"🚀 New version available! Local: {local_version}, Server: {server_version}. Starting update...")
            trigger_update()
        if "integrations" in data:
            settings["integrations"] = data["integrations"]
            save_settings(settings)
            print("💾 Updated local settings with server integration data.")
    except requests.exceptions.RequestException as e:
        print(f"❌ Network error during heartbeat: {e}")
    except json.JSONDecodeError:
        print("❌ Could not decode JSON from heartbeat response.")


def trigger_update():
    update_command = "curl -sS https://raw.githubusercontent.com/larsjarred9/silent-sound-doorbell-script/refs/heads/deployer/deployer.sh | sudo bash"
    print(f"🏃 Executing update command: {update_command}")
    try:
        subprocess.run(update_command, shell=True, check=True, text=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Update script failed with exit code {e.returncode}.\n stdout: {e.stdout}\n stderr: {e.stderr}")
    except Exception as e:
        print(f"❌ An unexpected error occurred during update: {e}")
    finally:
        print("...Exiting script to allow update to complete...")
        sys.exit()


def send_ring(serial_number):
    global last_ring_time
    current_time = time.time()
    if current_time - last_ring_time < RING_COOLDOWN:
        print("🚫 Ring event ignored due to cooldown.")
        return
    last_ring_time = current_time

    settings = load_or_create_settings()
    homewizard_ip = None
    integration_status = "inactive"
    if "integrations" in settings:
        for integration in settings["integrations"]:
            if integration.get("type") == "homewizard_socket":
                homewizard_ip = integration.get("credentials", {}).get("local_ip")
                break
    if homewizard_ip:
        if set_switch_state(homewizard_ip, {"power_on": True, "brightness": 255}):
            integration_status = "active"
            threading.Thread(target=blink_effect, args=(homewizard_ip,)).start()
        else:
            integration_status = "error"
    else:
        print("⚠️ HomeWizard IP not found in settings. Status is 'inactive'.")
        integration_status = "inactive"

    ring_url = f"{API_BASE_URL}/{serial_number}/ring"
    payload = {"status": integration_status}
    print(f"🔔 Sending ring event to: {ring_url} with payload: {json.dumps(payload)}")
    try:
        requests.post(ring_url, json=payload, headers=HEADERS, timeout=10).raise_for_status()
        print("✅ Ring event sent to server successfully.")
    except requests.exceptions.RequestException as e:
        print(f"❌ Network error during ring event: {e}")


def set_switch_state(ip_address, payload):
    state_url = f"http://{ip_address}/api/v1/state"
    print(f"💡 Sending state to {ip_address}: {json.dumps(payload)}")
    try:
        response = requests.put(state_url, json=payload, timeout=2)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException:
        return False


def blink_effect(ip_address, duration=60, interval=2.0):
    print(f"✨ Starting blink effect for {duration} seconds on {ip_address}")
    end_time = time.time() + duration
    is_dim = True
    while time.time() < end_time:
        time.sleep(interval)
        brightness = 50 if is_dim else 255
        if not set_switch_state(ip_address, {"brightness": brightness}):
            print("❌ Lost connection to switch during blink. Aborting effect.")
            break
        is_dim = not is_dim
    print(f"✨ Blink effect finished. Turning switch off.")
    set_switch_state(ip_address, {"power_on": False})


# --- GPIO Handling Section using Polling ---
def doorbell_polling_loop():
    """
    Monitors the doorbell GPIO pin using a polling loop.
    This method is used for maximum compatibility.
    """
    if not GPIO_AVAILABLE:
        print("ℹ️ GPIO not available, doorbell button polling thread will not start.")
        return

    # Setup GPIO within this thread
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(DOORBELL_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    print(f"✅ GPIO polling started for pin {DOORBELL_PIN}. Waiting for press...")

    while True:
        # Check if the button is pressed (input is LOW because of the pull-up resistor)
        if GPIO.input(DOORBELL_PIN) == GPIO.LOW:
            print(f"🔔 GPIO Pin {DOORBELL_PIN} was pressed!")
            if device_serial_number:
                # Call the main ring function, which has its own cooldown logic
                send_ring(device_serial_number)
            else:
                print("❌ Cannot send ring event, device serial number is not available.")
            # Wait 1 second after a press to allow the button to be released.
            # This is a simple debounce.
            time.sleep(1)

        # Wait a short time in every loop to prevent high CPU usage
        time.sleep(0.1)


# --- Main Execution ---
if __name__ == "__main__":
    try:
        settings = setup_device()
        device_serial_number = settings["serial_number"]

        # Start the new GPIO polling loop in a separate thread
        polling_thread = threading.Thread(target=doorbell_polling_loop, daemon=True)
        polling_thread.start()

        print("--- Device is running. Waiting for events. ---")

        while True:
            send_heartbeat(device_serial_number)
            print(f"--- Waiting for {HEARTBEAT_INTERVAL} seconds... ---")
            time.sleep(HEARTBEAT_INTERVAL)

    except (KeyboardInterrupt, SystemExit):
        print("\n--- Program interrupted. Shutting down. ---")
    finally:
        # Clean up GPIO resources on exit
        if GPIO_AVAILABLE:
            GPIO.cleanup()
        print("--- Shutdown complete. ---")
