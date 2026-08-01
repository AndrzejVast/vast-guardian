#!/usr/bin/env bash

set -e

echo "======================================"
echo "      Vast Guardian Installer"
echo "======================================"

echo
echo "=== SYSTEM ==="
uname -a

echo
echo "=== DOCKER ==="
docker --version

echo
echo "=== NVIDIA ==="
nvidia-smi --query-gpu=name,driver_version --format=csv

echo
echo "=== GIT ==="
git --version

echo
echo "=== VAST SERVICES ==="

for service in vastai docker ssh; do
    if systemctl is-active --quiet "$service"; then
        echo "OK  - $service działa"
    else
        echo "BŁĄD - $service nie działa"
    fi
done

echo
echo "=== DYSK ==="
df -h /

echo
echo "=== PAMIĘĆ ==="
free -h

echo
echo "Diagnostyka zakończona."
