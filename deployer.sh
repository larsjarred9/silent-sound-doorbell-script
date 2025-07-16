#!/bin/bash

set -e

echo "🔧 Installing Silent Sound Doorbell..."

# Constants
PROJECT_DIR="$HOME/silentdoorbell"
REPO_URL="https://github.com/larsjarred9/silent-sound-doorbell-script.git"
SERVICE_NAME="device.service"
SERVICE_FILE_PATH="/etc/systemd/system/$SERVICE_NAME"
REQUIREMENTS_FILE="$PROJECT_DIR/requirements.txt"

# 1. Ensure the project directory exists
if [ ! -d "$PROJECT_DIR" ]; then
    echo "📂 Creating project directory..."
    mkdir -p "$PROJECT_DIR"
fi

# 2. Clone or update repo
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

# 3. Install Python dependencies from requirements.txt
if [ -f "$REQUIREMENTS_FILE" ]; then
    echo "📦 Installing Python dependencies from requirements.txt..."
    pip3 install --user -r "$REQUIREMENTS_FILE"
else
    echo "ℹ️ No requirements.txt found, skipping pip install."
fi

# 4. Install systemd service
echo "🛠 Installing systemd service..."
sudo cp "$PROJECT_DIR/$SERVICE_NAME" "$SERVICE_FILE_PATH"

# 5. Enable and start the service
sudo systemctl daemon-reexec
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo "✅ Installation complete!"
echo "📂 Project directory: $PROJECT_DIR"
echo "📄 settings.txt: $PROJECT_DIR/settings.txt"
echo "🛠 Service file: $SERVICE_FILE_PATH"
echo "📜 Logs: journalctl -u $SERVICE_NAME -f"
