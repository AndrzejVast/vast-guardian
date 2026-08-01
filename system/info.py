#!/usr/bin/env python3

import subprocess

def cmd(command):
    try:
        return subprocess.check_output(command, shell=True, text=True).strip()
    except:
        return "UNKNOWN"

def gpu():
    return cmd("nvidia-smi --query-gpu=name --format=csv,noheader")

def docker():
    return cmd("systemctl is-active docker")

def vastai():
    return cmd("systemctl is-active vastai")

def hostname():
    return cmd("hostname")

def ip():
    return cmd("hostname -I | awk '{print $1}'")
