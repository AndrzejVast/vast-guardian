#!/usr/bin/env python3

from system.info import health


GPU_WARNING = 80
GPU_CRITICAL = 90
DISK_WARNING = 80
DISK_CRITICAL = 90


def check_alarms():

    h = health()
    alarms = []

    # Guardian
    if h["guardian"] != "active":
        alarms.append({
            "component": "Guardian",
            "level": "CRITICAL",
            "message": "Vast Guardian Web is not active"
        })

    # Docker
    if h["docker"] != "active":
        alarms.append({
            "component": "Docker",
            "level": "CRITICAL",
            "message": "Docker service is not active"
        })

    # Vast.ai
    if h["vastai"] != "active":
        alarms.append({
            "component": "VastAI",
            "level": "CRITICAL",
            "message": "Vast.ai service is not active"
        })

    # Internet
    if h["internet"] != "online":
        alarms.append({
            "component": "Internet",
            "level": "CRITICAL",
            "message": "Internet connection is offline"
        })

    # GPU temperature
    try:

        gpu_temp = int(h["gpu_temp"])

        if gpu_temp >= GPU_CRITICAL:

            alarms.append({
                "component": "GPU",
                "level": "CRITICAL",
                "message": f"GPU temperature is {gpu_temp}°C"
            })

        elif gpu_temp >= GPU_WARNING:

            alarms.append({
                "component": "GPU",
                "level": "WARNING",
                "message": f"GPU temperature is {gpu_temp}°C"
            })

    except (ValueError, TypeError):
        pass

    # Disk usage
    try:

        disk = int(h["disk"])

        if disk >= DISK_CRITICAL:

            alarms.append({
                "component": "Disk",
                "level": "CRITICAL",
                "message": f"Disk usage is {disk}%"
            })

        elif disk >= DISK_WARNING:

            alarms.append({
                "component": "Disk",
                "level": "WARNING",
                "message": f"Disk usage is {disk}%"
            })

    except (ValueError, TypeError):
        pass

    critical = sum(
        1 for alarm in alarms
        if alarm["level"] == "CRITICAL"
    )

    warnings = sum(
        1 for alarm in alarms
        if alarm["level"] == "WARNING"
    )

    if critical > 0:
        status = "CRITICAL"
    elif warnings > 0:
        status = "WARNING"
    else:
        status = "HEALTHY"

    return {
        "status": status,
        "critical": critical,
        "warnings": warnings,
        "count": len(alarms),
        "alarms": alarms
    }
