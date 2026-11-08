#!/bin/bash

# Mesly Dependency Installation Script
# Supports: Arch (pacman), Debian/Ubuntu (apt), Fedora (dnf), openSUSE (zypper)

set -e

echo "=================================="
echo "Mesly Dependency Installer"
echo "=================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Detect package manager
if command -v pacman &>/dev/null; then
  PKG_MANAGER="pacman"
  INSTALL_CMD="sudo pacman -S"
elif command -v apt &>/dev/null; then
  PKG_MANAGER="apt"
  INSTALL_CMD="sudo apt install -y"
elif command -v dnf &>/dev/null; then
  PKG_MANAGER="dnf"
  INSTALL_CMD="sudo dnf install -y"
elif command -v zypper &>/dev/null; then
  PKG_MANAGER="zypper"
  INSTALL_CMD="sudo zypper install -y"
else
  echo -e "${RED}Error: No supported package manager found (pacman, apt, dnf, zypper)${NC}"
  exit 1
fi

echo -e "${GREEN}Detected package manager: ${PKG_MANAGER}${NC}"
echo ""

# Update package database
echo -e "${YELLOW}Updating package database...${NC}"
case $PKG_MANAGER in
pacman)
  sudo pacman -Sy
  ;;
apt)
  sudo apt update
  ;;
dnf)
  sudo dnf check-update || true
  ;;
zypper)
  sudo zypper refresh
  ;;
esac

echo ""
echo -e "${YELLOW}Installing system dependencies...${NC}"

# Install system dependencies based on package manager
case $PKG_MANAGER in
pacman)
  # Arch Linux / Manjaro
  $INSTALL_CMD python python-pip tk \
    gnome-screenshot scrot \
    qt5-base \
    wmctrl xdotool \
    python-gobject gstreamer gst-plugins-base gst-plugin-pipewire xdg-desktop-portal \
    tesseract tesseract-data-eng tesseract-data-chi_sim tesseract-data-jpn ||
    echo -e "${YELLOW}Some packages may already be installed${NC}"
  ;;

apt)
  # Debian / Ubuntu
  $INSTALL_CMD python3 python3-pip python3-tk \
    gnome-screenshot scrot \
    python3-pyqt5 \
    wmctrl xdotool \
    python3-gi gir1.2-gst-plugins-base-1.0 gstreamer1.0-plugins-base gstreamer1.0-pipewire xdg-desktop-portal \
    tesseract-ocr tesseract-ocr-eng tesseract-ocr-chi-sim tesseract-ocr-jpn \
    python3-dev build-essential ||
    echo -e "${YELLOW}Some packages may already be installed${NC}"
  ;;

dnf)
  # Fedora
  $INSTALL_CMD python3 python3-pip python3-tkinter \
    gnome-screenshot scrot \
    python3-qt5 \
    wmctrl xdotool \
    python3-gobject gstreamer1-plugins-base gstreamer1-pipewire xdg-desktop-portal \
    tesseract tesseract-langpack-eng tesseract-langpack-chi-sim tesseract-langpack-jpn \
    python3-devel gcc ||
    echo -e "${YELLOW}Some packages may already be installed${NC}"
  ;;

zypper)
  # openSUSE
  $INSTALL_CMD python3 python3-pip python3-tk \
    gnome-screenshot scrot \
    python3-qt5 \
    wmctrl xdotool \
    python3-gobject gstreamer-plugins-base pipewire-gstreamer-plugin xdg-desktop-portal \
    tesseract-ocr tesseract-ocr-traineddata-english tesseract-ocr-traineddata-chinese_sim tesseract-ocr-traineddata-japanese \
    python3-devel gcc ||
    echo -e "${YELLOW}Some packages may already be installed${NC}"
  ;;
esac

echo ""
echo -e "${GREEN}System dependencies installed successfully!${NC}"
