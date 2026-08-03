#!/usr/bin/env python3

import subprocess
import shutil


def cmd(command):
    try:
        return subprocess.check_output(
            command,
            shell=True,
            text=True
        ).strip()
    except Exception:
        return "UNKNOWN"


def service_status(service):
    return cmd(f"systemctl is-active {service}")


def gpu():
    return cmd("nvidia-smi --query-gpu=name --format=csv,noheader")


def gpu_temp():
    return cmd("nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits")


def docker():
    return service_status("docker")


def vastai():
    return service_status("vastai")


def guardian():
    return service_status("vast-guardian-web")


def hostname():
    return cmd("hostname")


def ip():
    return cmd("hostname -I | awk '{print $1}'")


def uptime():
    return cmd("uptime -p")


def disk_usage():
    usage = shutil.disk_usage("/")
    return round((usage.used / usage.total) * 100)


def internet():
    try:
        subprocess.check_output(
            ["ping", "-c", "1", "-W", "2", "1.1.1.1"],
            stderr=subprocess.DEVNULL
        )
        return "online"
    except Exception:
        return "offline"


def health():

    return {
        "guardian": guardian(),
        "docker": docker(),
        "vastai": vastai(),
        "internet": internet(),
        "hostname": hostname(),
        "ip": ip(),
        "gpu": gpu(),
        "gpu_temp": gpu_temp(),
        "disk": disk_usage(),
        "uptime": uptime()
    }
def health_summary():

    h = health()

    problems = []

    if h["guardian"] != "active":
        problems.append("Guardian")

    if h["docker"] != "active":
        problems.append("Docker")

    if h["vastai"] != "active":
        problems.append("VastAI")

    if h["internet"] != "online":
        problems.append("Internet")

    try:
        if int(h["gpu_temp"]) >= 80:
            problems.append("GPU Temperature")
    except Exception:
        pass

    try:
        if int(h["disk"]) >= 90:
            problems.append("Disk Usage")
    except Exception:
        pass

    return {
        "healthy": len(problems) == 0,
        "problems": problems,
        "count": len(problems)
    }
