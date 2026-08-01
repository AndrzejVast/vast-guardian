#!/usr/bin/env bash

LOGFILE="$HOME/vast-guardian/logs/repair.log"

echo "==============================" >> "$LOGFILE"
echo "$(date)" >> "$LOGFILE"

if systemctl is-active --quiet vastai; then
    echo "vastai: OK" >> "$LOGFILE"
else
    echo "vastai: RESTART" >> "$LOGFILE"
    sudo systemctl restart vastai
fi

if systemctl is-active --quiet docker; then
    echo "docker: OK" >> "$LOGFILE"
else
    echo "docker: RESTART" >> "$LOGFILE"
    sudo systemctl restart docker
fi

if nvidia-smi >/dev/null 2>&1; then
    echo "gpu: OK" >> "$LOGFILE"
else
    echo "gpu: ERROR" >> "$LOGFILE"
fi

echo >> "$LOGFILE"
