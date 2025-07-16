#!/bin/bash

# Check if git is installed, install if missing
if ! command -v git &> /dev/null; then
  echo "❌ Git not found. Installing git... 🛠️"
  if command -v apt &> /dev/null; then
    echo "📦 Updating package list..."
    sudo apt update
    echo "⬇️ Installing git package..."
    sudo apt install git -y
    echo "✅ Git installed successfully!"
  else
    echo "⚠️ Package manager apt not found. Please install git manually."
    exit 1
  fi
else
  echo "✅ Git is already installed. 👍"
fi

# Check if python3 is installed, install if missing
if ! command -v python3 &> /dev/null; then
  echo "❌ Python 3 not found. Installing python3... 🐍"
  if command -v apt &> /dev/null; then
    echo "📦 Updating package list..."
    sudo apt update
    echo "⬇️ Installing python3..."
    sudo apt install python3 -y
    echo "✅ python3 installed successfully!"
  else
    echo "⚠️ Package manager apt not found. Please install python3 manually."
    exit 1
  fi
else
  echo "✅ python3 is already installed. 👍"
fi

# Check if pip3 is installed, install if missing
if ! command -v pip3 &> /dev/null; then
  echo "❌ pip3 not found. Installing python3-pip... 🛠️"
  if command -v apt &> /dev/null; then
    echo "📦 Updating package list..."
    sudo apt update
    echo "⬇️ Installing python3-pip package..."
    sudo apt install python3-pip -y
    echo "✅ pip3 installed successfully!"
  else
    echo "⚠️ Package manager apt not found. Please install pip3 manually."
    exit 1
  fi
else
  echo "✅ pip3 is already installed. 👍"
fi

set -e

echo "🔧 Installing Silent Sound Doorbell..."

# Constants
PROJECT_DIR="/var/silentdoorbell/"
REPO_URL="https://github.com/larsjarred9/silent-sound-doorbell-script.git"
SERVICE_NAME="device.service"
SERVICE_FILE_PATH="/etc/systemd/system/$SERVICE_NAME"
REQUIREMENTS_FILE="$PROJECT_DIR/requirements.txt"

# Ensure the project directory exists
if [ ! -d "$PROJECT_DIR" ]; then
    echo "📂 Creating project directory..."
    mkdir -p "$PROJECT_DIR"
fi

# Clone or update repo
if [ -d "$PROJECT_DIR/.git" ]; then
    echo "🔄 Updating existing Git repo..."
    cd "$PROJECT_DIR"
    git pull
else
    if [ "$(ls -A "$PROJECT_DIR")" ]; then
        echo "⚠️ Directory exists but is not a Git repo. Aborting to prevent overwrite."
        exit 1
    else
        echo "📥 Cloning repo to $PROJECT_DIR..."
        git clone "$REPO_URL" "$PROJECT_DIR"
    fi
fi

# Install Python dependencies
if [ -f "$REQUIREMENTS_FILE" ]; then
    echo "📦 Installing Python dependencies from requirements.txt..."
    pip3 install --user -r "$REQUIREMENTS_FILE"
else
    echo "ℹ️ No requirements.txt found, skipping pip install."
fi

# Install systemd service file (dynamic with %u and %h already in repo version)
if [ -f "$PROJECT_DIR/$SERVICE_NAME" ]; then
    echo "🛠 Installing systemd service..."
    sudo cp "$PROJECT_DIR/$SERVICE_NAME" "$SERVICE_FILE_PATH"
else
    echo "❌ Service file $SERVICE_NAME not found in repo. Aborting."
    exit 1
fi

# Enable and start the service
echo "🚀 Enabling and starting service..."
sudo systemctl daemon-reexec
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo "✅ Installation complete!"
echo "📂 Project directory: $PROJECT_DIR"
echo "📄 settings.txt: $PROJECT_DIR/settings.txt"
echo "🛠 Service file: $SERVICE_FILE_PATH"
echo "📜 View logs: journalctl -u $SERVICE_NAME -f"
