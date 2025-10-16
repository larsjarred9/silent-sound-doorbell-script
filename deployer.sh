#!/bin/bash

# --- 1. Initial Dependency Checks ---
echo "🔎 Checking initial dependencies..."

# List of essential apt packages
essential_packages=(git python3 python3-pip python3-venv python3-rpi.gpio)

for pkg in "${essential_packages[@]}"; do
  if ! dpkg -l | grep -q "ii  $pkg "; then
    echo "❌ $pkg not found. Installing..."
    sudo apt-get update
    sudo apt-get install -y "$pkg"
  else
    echo "✅ $pkg is already installed."
  fi
done

# List of packages needed to build the Pillow library
pillow_deps=(build-essential python3-dev libjpeg-dev zlib1g-dev)

echo "🔎 Checking Pillow build dependencies..."
for pkg in "${pillow_deps[@]}"; do
  if ! dpkg -l | grep -q "ii  $pkg "; then
    echo "❌ $pkg not found. Installing..."
    sudo apt-get update
    sudo apt-get install -y "$pkg"
  else
    echo "✅ $pkg is already installed."
  fi
done

set -e # Exit script if any command fails from here on

# --- 2. Hardware Configuration ---
echo "⚙️ Configuring Raspberry Pi Hardware Interface..."

# Enable I2C interface non-interactively
if ! raspi-config nonint get_i2c | grep -q "0"; then
  echo "🔧 Enabling I2C interface..."
  sudo raspi-config nonint do_i2c 0
  NEEDS_REBOOT=true
else
  echo "✅ I2C is already enabled."
fi

# Set I2C baud rate for stability if not already set
BAUDRATE_CONFIG="dtparam=i2c_arm_baudrate=100000"
CONFIG_FILE="/boot/config.txt"
if ! grep -q "^${BAUDRATE_CONFIG}" "$CONFIG_FILE"; then
  echo "🔧 Setting I2C baud rate to 100kHz for stability..."
  echo "${BAUDRATE_CONFIG}" | sudo tee -a "$CONFIG_FILE" > /dev/null
  NEEDS_REBOOT=true
else
  echo "✅ I2C baud rate is already configured."
fi

# Add current user to the i2c group for permissions
if ! groups "$USER" | grep -q '\bi2c\b'; then
  echo "🔧 Adding user $USER to the 'i2c' group..."
  sudo usermod -aG i2c "$USER"
  NEEDS_REBOOT=true
else
  echo "✅ User $USER is already in the 'i2c' group."
fi

# --- 3. Project Setup & Installation ---
echo "🔧 Installing Silent Sound Doorbell..."

# Constants
PROJECT_DIR="/var/silentdoorbell"
VENV_DIR="$PROJECT_DIR/.venv"
REPO_URL="https://github.com/larsjarred9/silent-sound-doorbell-script.git"
SERVICE_NAME="device.service"
SERVICE_FILE_PATH="/etc/systemd/system/$SERVICE_NAME"
REQUIREMENTS_FILE="$PROJECT_DIR/requirements.txt"

# Ensure the project directory exists and set correct permissions
# We define the owner user here. SUDO_USER is the person who ran sudo.
OWNER_USER=${SUDO_USER:-$(whoami)}
if [ ! -d "$PROJECT_DIR" ]; then
    echo "📂 Creating project directory..."
    sudo mkdir -p "$PROJECT_DIR"
    sudo chown -R "$OWNER_USER:$OWNER_USER" "$PROJECT_DIR"
fi

cd "$PROJECT_DIR"

# Clone or update repo. This logic is now corrected.
if [ -d ".git" ]; then
    echo "🔄 Updating existing Git repo..."
    # Check if settings exists if so protect it from being overwritten
    if [ -f "settings.txt" ]; then
        echo "🔒 Protecting local settings.txt from being overwritten..."
        sudo -u "$OWNER_USER" git update-index --assume-unchanged settings.txt
    fi
    # Run git commands as the directory owner to avoid permission issues
    sudo -u "$OWNER_USER" git pull
else
    echo "📥 Cloning repo into the new directory..."
    # Clone into the current empty directory (.)
    sudo -u "$OWNER_USER" git clone "$REPO_URL" .
fi

# Create and populate Python virtual environment
if [ ! -d "$VENV_DIR" ]; then
  echo "🐍 Creating Python virtual environment..."
  # Run as owner to ensure venv is owned correctly
  sudo -u "$OWNER_USER" python3 -m venv "$VENV_DIR"
fi

# Install Python dependencies into the virtual environment
if [ -f "$REQUIREMENTS_FILE" ]; then
    echo "📦 Installing Python dependencies from requirements.txt..."
    # The pip command itself doesn't need sudo as it writes to the owned venv
    "$VENV_DIR/bin/pip" install -r "$REQUIREMENTS_FILE"
else
    echo "ℹ️ No requirements.txt found, skipping pip install."
fi

# --- 4. Service Setup ---
# Install systemd service file
if [ -f "$PROJECT_DIR/$SERVICE_NAME" ]; then
    echo "🛠️ Installing systemd service..."
    sudo cp "$PROJECT_DIR/$SERVICE_NAME" "$SERVICE_FILE_PATH"
else
    echo "❌ Service file $SERVICE_NAME not found in repo. Aborting."
    exit 1
fi

# Enable and start the service
echo "🚀 Enabling and starting service..."
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

# --- 5. Final Instructions ---
echo "✅ Installation complete!"
echo "📂 Project directory: $PROJECT_DIR"
echo "🛠️ Service file: $SERVICE_FILE_PATH"
echo "📜 View logs: journalctl -u $SERVICE_NAME -f"

if [ "$NEEDS_REBOOT" = true ]; then
  echo -e "\n\n⚠️ IMPORTANT: A reboot is required for hardware changes to take effect."
  echo "Please run 'sudo reboot' now."
fi