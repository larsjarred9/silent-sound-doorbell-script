# this is the latest working version we made togheter
# when GPIO19 (Pin 35) is pressed, we should send a ring event (prevent holding the button)
# also tell me what to put in requirements.txt since we prob need to use external libraries :)

# --- Imports ---
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


# --- Configuration ---
BASE_DIR = Path("/var/silentdoorbell")
SETTINGS_FILE = BASE_DIR / "settings.txt"
API_BASE_URL = "http://192.168.68.114/api/devices"
HEARTBEAT_INTERVAL = 180  # 3 minutes
RETRY_INTERVAL = 60  # 1 minute
RING_COOLDOWN = 60  # 60 seconds to prevent spamming ring events
DOORBELL_PIN = 19   # GPIO pin (BCM numbering) for the button, corresponds to physical pin 35.

DEFAULT_SETTINGS = {
    "device_type_id": 1,
    "version": "0.1"
}

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}


# --- Global State ---
last_ring_time = 0
device_serial_number = None  #


# --- Helper Functions ---
def load_or_create_settings():
    """
    Loads settings from the settings file. If the file doesn't exist,
    it creates it with the default settings.
    """
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
    """
    Ensures the device has a serial number, requesting one from the server if needed.
    """
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
        print(f" stdout: {e.stdout}")
        print(f" stderr: {e.stderr}")
    except Exception as e:
        print(f"❌ An unexpected error occurred during update: {e}")
    finally:
        print("...Exiting script to allow update to complete...")
        sys.exit()


def send_ring(serial_number):
    """Determines local integration status, triggers the effect, and notifies the server."""
    global last_ring_time
    current_time = time.time()

    if current_time - last_ring_time < RING_COOLDOWN:
        print("🚫 Ring event ignored due to cooldown.")
        return

    last_ring_time = current_time

    # --- 1. Determine local integration status ---
    settings = load_or_create_settings()
    homewizard_ip = None
    integration_status = "inactive"  # Default status

    if "integrations" in settings:
        for integration in settings["integrations"]:
            if integration.get("type") == "homewizard_socket":
                homewizard_ip = integration.get("credentials", {}).get("local_ip")
                break

    if homewizard_ip:
        # Try to activate the switch. This action determines the status.
        if set_switch_state(homewizard_ip, {"power_on": True, "brightness": 255}):
            integration_status = "active"
            # If successful, start the blinking effect in a separate thread
            threading.Thread(target=blink_effect, args=(homewizard_ip,)).start()
        else:
            integration_status = "error"
    else:
        print("⚠️ HomeWizard IP not found in settings. Status is 'inactive'.")
        integration_status = "inactive"

    # --- 2. Notify the main server with the determined status ---
    ring_url = f"{API_BASE_URL}/{serial_number}/ring"
    payload = {"status": integration_status}
    print(f"🔔 Sending ring event to: {ring_url} with payload: {json.dumps(payload)}")
    try:
        requests.post(ring_url, json=payload, headers=HEADERS, timeout=10).raise_for_status()
        print("✅ Ring event sent to server successfully.")
    except requests.exceptions.RequestException as e:
        print(f"❌ Network error during ring event: {e}")


def set_switch_state(ip_address, payload):
    """Sends a command payload to a HomeWizard smart switch."""
    state_url = f"http://{ip_address}/api/v1/state"
    print(f"💡 Sending state to {ip_address}: {json.dumps(payload)}")
    try:
        response = requests.put(state_url, json=payload, timeout=2)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException:
        # Don't print error here to avoid spamming the log during blinking
        return False


def blink_effect(ip_address, duration=60, interval=2.0):
    """Controls the blinking effect of a switch for a given duration."""
    print(f"✨ Starting blink effect for {duration} seconds on {ip_address}")

    end_time = time.time() + duration
    is_dim = True  # Start by dimming since it's already at max brightness
    while time.time() < end_time:
        time.sleep(interval)
        brightness = 50 if is_dim else 255
        if not set_switch_state(ip_address, {"brightness": brightness}):
            print("❌ Lost connection to switch during blink. Aborting effect.")
            break  # Exit the loop if we can't communicate with the switch
        is_dim = not is_dim

    print(f"✨ Blink effect finished. Turning switch off.")
    set_switch_state(ip_address, {"power_on": False})


# --- NEW: GPIO Handling Section ---
def button_pressed_callback(channel):
    """Callback function triggered by the button press event."""
    print(f"🔔 GPIO Pin {channel} pressed! Triggering ring event...")
    if device_serial_number:
        send_ring(device_serial_number)
    else:
        print("❌ Cannot send ring event, device serial number is not available.")

def setup_gpio():
    """Sets up the GPIO pin for the doorbell button."""
    if not GPIO_AVAILABLE:
        return  # Do nothing if GPIO library isn't available

    print(f"🔌 Setting up GPIO pin {DOORBELL_PIN} for doorbell button...")
    GPIO.setmode(GPIO.BCM)
    # Setup pin as input with an internal pull-up resistor.
    # The button should connect the pin to GND when pressed.
    GPIO.setup(DOORBELL_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    # Add event detection for a falling edge (high-to-low signal on press)
    # bouncetime prevents multiple triggers from a single noisy press
    GPIO.add_event_detect(DOORBELL_PIN, GPIO.FALLING, callback=button_pressed_callback, bouncetime=500)
    print("✅ GPIO ready. Waiting for button press.")

def cleanup_gpio():
    """Cleans up GPIO resources on exit."""
    if GPIO_AVAILABLE:
        print("🧹 Cleaning up GPIO resources.")
        GPIO.cleanup()


def command_listener():
    """Listens for user commands like 'ring' or 'exit' in a separate thread."""
    while True:
        try:
            command = input()
            if command.lower() == "ring":
                print("⌨️ Manual ring command received.")
                if device_serial_number:
                    send_ring(device_serial_number)
                else:
                    print("❌ Cannot ring, device not initialized.")
            elif command.lower() == "exit":
                print("...Exiting program...")
                # Use os._exit for a hard stop, necessary when threads are running
                os._exit(0)
        except (EOFError, KeyboardInterrupt):
            print("\n...Exiting program...")
            os._exit(0)


# --- Main Execution ---
if __name__ == "__main__":
    try:
        settings = setup_device()
        device_serial_number = settings["serial_number"]  # Set the global serial number

        # Start the command listener in a separate thread
        listener_thread = threading.Thread(target=command_listener, daemon=True)
        listener_thread.start()

        # NEW: Setup GPIO now that we have the serial number
        setup_gpio()

        print("--- Device is running. Waiting for events. ---")
        print("--- Type 'ring' to test, or 'exit' to quit. ---")

        while True:
            send_heartbeat(device_serial_number)
            print(f"--- Waiting for {HEARTBEAT_INTERVAL} seconds... ---")
            time.sleep(HEARTBEAT_INTERVAL)

    except (KeyboardInterrupt, SystemExit):
        print("\n--- Program interrupted. Shutting down. ---")
    finally:

        cleanup_gpio()
        print("--- Shutdown complete. ---")