import subprocess
import time

while True:
    subprocess.run(["python3", "collector/collect.py"])
    time.sleep(5)
