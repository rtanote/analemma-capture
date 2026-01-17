#!/bin/bash
# Analemma Solar Capture System - Installation Script
# Run with: sudo ./scripts/install.sh

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Analemma Solar Capture System Installer${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check if running as root for system-wide installation
if [ "$EUID" -ne 0 ]; then
    echo -e "${YELLOW}Note: Running without sudo. System files will not be installed.${NC}"
    echo -e "${YELLOW}Run with 'sudo' for full installation.${NC}"
    echo ""
    SUDO_INSTALL=false
else
    SUDO_INSTALL=true
fi

# Get the script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "Project directory: $PROJECT_DIR"
echo ""

# Check for Python 3.9+
echo "Checking Python version..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
    PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

    if [ "$PYTHON_MAJOR" -ge 3 ] && [ "$PYTHON_MINOR" -ge 9 ]; then
        echo -e "  ${GREEN}Python $PYTHON_VERSION found${NC}"
    else
        echo -e "  ${RED}Python 3.9+ required, found $PYTHON_VERSION${NC}"
        exit 1
    fi
else
    echo -e "  ${RED}Python 3 not found${NC}"
    exit 1
fi

# Install system dependencies
if [ "$SUDO_INSTALL" = true ]; then
    echo ""
    echo "Installing system dependencies..."
    apt-get update
    apt-get install -y libusb-1.0-0-dev libjpeg-dev zlib1g-dev libpng-dev
    echo -e "  ${GREEN}System dependencies installed${NC}"
fi

# Install udev rules
if [ "$SUDO_INSTALL" = true ]; then
    echo ""
    echo "Installing udev rules..."
    cp "$PROJECT_DIR/systemd/99-zwo.rules" /etc/udev/rules.d/
    udevadm control --reload-rules
    udevadm trigger
    echo -e "  ${GREEN}udev rules installed${NC}"
fi

# Create virtual environment
echo ""
echo "Setting up Python virtual environment..."
cd "$PROJECT_DIR"

if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo -e "  ${GREEN}Virtual environment created${NC}"
else
    echo -e "  ${YELLOW}Virtual environment already exists${NC}"
fi

# Activate and install package
echo ""
echo "Installing analemma-capture package..."
source venv/bin/activate
pip install --upgrade pip
pip install -e .
echo -e "  ${GREEN}Package installed${NC}"

# Create directories
echo ""
echo "Creating directories..."
mkdir -p /home/pi/analemma/images
mkdir -p /home/pi/.analemma

if [ "$SUDO_INSTALL" = true ]; then
    mkdir -p /var/log/analemma
    chown pi:pi /var/log/analemma
fi

echo -e "  ${GREEN}Directories created${NC}"

# Copy configuration file
echo ""
echo "Setting up configuration..."
if [ ! -f "$PROJECT_DIR/config/config.yaml" ]; then
    cp "$PROJECT_DIR/config/config.example.yaml" "$PROJECT_DIR/config/config.yaml"
    echo -e "  ${GREEN}Configuration file created: config/config.yaml${NC}"
    echo -e "  ${YELLOW}Please edit config/config.yaml to customize settings${NC}"
else
    echo -e "  ${YELLOW}Configuration file already exists${NC}"
fi

# Install systemd service
if [ "$SUDO_INSTALL" = true ]; then
    echo ""
    echo "Installing systemd service..."
    cp "$PROJECT_DIR/systemd/analemma-capture.service" /etc/systemd/system/
    systemctl daemon-reload
    echo -e "  ${GREEN}systemd service installed${NC}"

    echo ""
    echo -e "${YELLOW}To enable auto-start on boot:${NC}"
    echo "  sudo systemctl enable analemma-capture"
    echo ""
    echo -e "${YELLOW}To start the service now:${NC}"
    echo "  sudo systemctl start analemma-capture"
fi

# Add user to video group
if [ "$SUDO_INSTALL" = true ]; then
    echo ""
    echo "Adding user to video group..."
    usermod -a -G video pi
    echo -e "  ${GREEN}User 'pi' added to video group${NC}"
    echo -e "  ${YELLOW}Note: You may need to log out and back in for group changes to take effect${NC}"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Installation complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Quick start:"
echo "  1. Edit configuration: nano config/config.yaml"
echo "  2. Test camera: analemma camera-info"
echo "  3. Test capture: analemma capture"
echo "  4. Start daemon: analemma daemon"
echo ""
echo "For full documentation, see README.md"
