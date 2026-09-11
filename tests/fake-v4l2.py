#!/usr/bin/env python3
"""Fake utility: only synthetic state files, never opens its /dev/ argument."""
import json
import os
from pathlib import Path
import re
import sys
import time

state_path = Path(os.environ["FAKE_CAMERA_STATE"])
if os.environ.get("FAKE_CAMERA_TIMEOUT"):
    time.sleep(10)
if os.environ.get("FAKE_CAMERA_OFFLINE"):
    sys.exit(1)
state = json.loads(state_path.read_text())
if sys.argv[3] == "--set-ctrl":
    name, value = sys.argv[4].split("=")
    state[name] = int(value)
    state_path.write_text(json.dumps(state))
    with Path(os.environ["FAKE_CAMERA_WRITES"]).open("a") as out:
        out.write(sys.argv[4] + "\n")
else:
    text = (Path(__file__).parent / "camera.txt").read_text()
    relations = {"focus_absolute": "focus_automatic_continuous", "white_balance_temperature": "white_balance_automatic", "exposure_time_absolute": "auto_exposure"}
    for line in text.splitlines():
        name = line.strip().split(" ")[0]
        if name in state:
            line = re.sub(r"value=-?\d+", f"value={state[name]}", line)
        if name in relations and state.get(relations[name]) in (0, 1 if name == "exposure_time_absolute" else 0):
            line = line.replace("inactive, ", "")
        print(line)
