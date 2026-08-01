#!/usr/bin/env bash

LOGFILE="$HOME/vast-guardian/logs/health.log"

mkdir -p "$(dirname "$LOGFILE")"

echo "==============================" >> "$LOGFILE"
echo "$(date)" >> "$LOGFILE"

systemctl is-active vastai >> "$LOGFILE"
systemctl is-active docker >> "$LOGFILE"

if nvidia-smi > /dev/null 2>&1; then
    echo "GPU: OK" >> "$LOGFILE"
else
    echo "GPU: ERROR" >> "$LOGFILE"
fi

echo >> "$LOGFILE"
