#!/usr/bin/env python3

import subprocess
from datetime import datetime

def status(service):
    result = subprocess.run(
        ["systemctl", "is-active", service],
        capture_output=True,
        text=True
    )
    return result.stdout.strip()

print("=" * 40)
print("      Vast Guardian v0.1")
print("=" * 40)
print("Data:", datetime.now())
print()

print("Docker :", status("docker"))
print("VastAI :", status("vastai"))

gpu = subprocess.run(
    ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
    capture_output=True,
    text=True
)

print("GPU    :", gpu.stdout.strip())
