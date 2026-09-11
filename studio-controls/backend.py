#!/usr/bin/env python3
"""Configured camera/light controls. No discovery or read operation writes devices."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

LIMIT = 1024 * 1024
TIMEOUT = 3
IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,79}$")
CONTROL = re.compile(r"^\s*(\w+)\s+0x[0-9a-fA-F]+\s+\(([^)]+)\)\s*:\s*(.*)$")


class ControlError(Exception):
    pass


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ControlError("Expected a finite number")
    return value


def integer(value):
    if number(value) != int(value):
        raise ControlError("Expected an integer in device units")
    return int(value)


def identifier(value):
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise ControlError("Invalid identifier")
    return value


def validate(config):
    if not isinstance(config, dict):
        raise ControlError("Configuration must be an object")
    for key in ("devices", "controls", "actions"):
        rows = config.setdefault(key, [])
        if not isinstance(rows, list) or len(rows) > 128:
            raise ControlError(f"Invalid {key} list")
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ControlError(f"Invalid {key} entry")
            name = identifier(row.get("id"))
            if name in seen:
                raise ControlError(f"Duplicate {key} id: {name}")
            seen.add(name)
    devices = {d["id"]: d for d in config["devices"]}
    for device in devices.values():
        if device.get("type") == "v4l2":
            path = device.get("path")
            if not isinstance(path, str) or not path.startswith("/dev/") or "\x00" in path:
                raise ControlError("Camera requires an absolute /dev/ path")
        elif device.get("type") == "key-light":
            url = urllib.parse.urlsplit(device.get("url", ""))
            if url.scheme != "http" or not url.hostname or url.username or url.password or url.fragment:
                raise ControlError("Key Light requires an explicit credential-free HTTP URL")
        else:
            raise ControlError("Unsupported device type")
    controls = {c["id"]: c for c in config["controls"]}
    for control in controls.values():
        if control.get("device") not in devices:
            raise ControlError("Unknown control device")
        identifier(control.get("control"))
        for field in ("label", "group", "unit"):
            if field in control and not isinstance(control[field], str):
                raise ControlError(f"Invalid {field}")
        if "step" in control and integer(control["step"]) <= 0:
            raise ControlError("Step must be positive")
        if control.get("display", "raw") not in ("raw", "exposure100us"):
            raise ControlError("Unsupported value display")
        if control.get("slider", "linear") not in ("linear", "log"):
            raise ControlError("Unsupported slider scale")
        if "default" in control:
            integer(control["default"])
        if "toggleValues" in control:
            values = control["toggleValues"]
            if not isinstance(values, list) or len(values) != 2 or integer(values[0]) == integer(values[1]):
                raise ControlError("toggleValues must contain two distinct integers")
        if "powerOnChange" in control and (not isinstance(control["powerOnChange"], bool) or devices[control["device"]]["type"] != "key-light" or control["control"] == "power"):
            raise ControlError("powerOnChange is boolean policy for light brightness/temperature only")
        relation = control.get("enabledWhen")
        if relation is not None:
            if not isinstance(relation, dict) or relation.get("control") not in controls:
                raise ControlError("Invalid enabledWhen control")
            integer(relation.get("equals"))
            if controls[relation["control"]].get("device") != control["device"]:
                raise ControlError("Cross-device automatic dependencies are unsupported")
    for action in config["actions"]:
        if action.get("control") not in controls or action.get("operation") not in ("set", "adjust", "toggle", "reset"):
            raise ControlError("Invalid configured action")
        if action["operation"] in ("set", "adjust"):
            integer(action.get("value"))
    bar = config.get("bar", {})
    if not isinstance(bar, dict):
        raise ControlError("Invalid bar configuration")
    actions = {a["id"] for a in config["actions"]}
    for field in ("rightClickAction", "scrollUpAction", "scrollDownAction"):
        if field in bar and bar[field] not in actions:
            raise ControlError("Unknown bar action")
    interval = integer(config.get("pollIntervalMs", 5000))
    if not 1000 <= interval <= 3600000:
        raise ControlError("pollIntervalMs must be 1000..3600000")
    return config


def parse_controls(text):
    result = {}
    current = None
    for line in text.splitlines():
        match = CONTROL.match(line)
        if match:
            name, kind, details = match.groups()
            current = None
            if kind not in ("int", "bool", "menu", "intmenu"):
                continue
            attrs = {k: int(v) for k, v in re.findall(r"\b(min|max|step|default|value)=(-?\d+)", details)}
            flags = details.split("flags=", 1)[1].strip().split(", ") if "flags=" in details else []
            if "value" not in attrs:
                continue
            if kind == "bool":
                attrs.update(min=0, max=1, step=1)
            if kind in ("menu", "intmenu"):
                attrs.setdefault("step", 1)
            if not all(k in attrs for k in ("min", "max", "step")) or attrs["step"] <= 0:
                continue
            current = {**attrs, "kind": "menu" if kind == "intmenu" else kind, "flags": flags, "options": []}
            result[name] = current
        elif current is not None and current["kind"] == "menu":
            menu = re.match(r"\s*(-?\d+):\s*(.*)$", line)
            if menu:
                current["options"].append({"value": int(menu[1]), "label": menu[2]})
    return result


def v4l2(device, *args):
    try:
        # A fixed executable and argument vector, never a shell or user command string.
        process = subprocess.Popen([os.environ.get("V4L2_CTL", "v4l2-ctl"), "--device", device["path"], *args],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={**os.environ, "LC_ALL": "C"})
        output = bytearray()
        total = 0
        deadline = time.monotonic() + TIMEOUT
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                selector.register(process.stderr, selectors.EVENT_READ)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ControlError("Camera query timed out")
                    for key, _ in selector.select(remaining):
                        chunk = os.read(key.fileobj.fileno(), 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        total += len(chunk)
                        if total > LIMIT:
                            raise ControlError("Camera response too large")
                        if key.fileobj is process.stdout:
                            output.extend(chunk)
            try:
                process.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                raise ControlError("Camera query timed out") from None
            if process.returncode:
                raise ControlError("Camera unavailable or control request rejected")
            return output.decode("utf-8", errors="replace")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdout.close()
            process.stderr.close()
    except OSError as error:
        raise ControlError("Camera utility unavailable") from error


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


@contextlib.contextmanager
def network_deadline():
    # Linux helper process: bound DNS + connect + the entire body, including slow drips.
    def expired(_signum, _frame):
        raise ControlError("Key Light request timed out")
    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, TIMEOUT)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def light_request(device, values=None):
    data = None if values is None else json.dumps({"numberOfLights": 1, "lights": [values]}).encode()
    request = urllib.request.Request(device["url"], data=data, headers={"Content-Type": "application/json"},
                                     method="GET" if data is None else "PUT")
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with network_deadline():
            with opener.open(request, timeout=TIMEOUT) as response:
                raw = response.read(LIMIT + 1)
        if len(raw) > LIMIT:
            raise ValueError("oversized response")
        lights = json.loads(raw)["lights"]
        light = lights[0]
        for field in ("on", "brightness", "temperature"):
            integer(light[field])
        if light["on"] not in (0, 1) or not 0 <= light["brightness"] <= 100 or not 143 <= light["temperature"] <= 344:
            raise ValueError("invalid light state")
        return light
    except (OSError, ValueError, KeyError, IndexError, TypeError, ControlError) as error:
        if isinstance(error, urllib.error.HTTPError):
            error.close()
        raise ControlError("Key Light unavailable or invalid response") from error


def discover(device):
    if device["type"] == "v4l2":
        return parse_controls(v4l2(device, "--list-ctrls-menus"))
    light = light_request(device)
    return {
        "power": {"kind": "bool", "min": 0, "max": 1, "step": 1, "value": light["on"], "flags": [], "options": []},
        "brightness": {"kind": "int", "min": 0, "max": 100, "step": 1, "value": light["brightness"], "flags": [], "options": []},
        "temperature": {"kind": "int", "min": 2900, "max": 7000, "step": 1, "value": round(1000000 / light["temperature"]), "flags": [], "options": []},
    }


@contextlib.contextmanager
def device_lock(device):
    directory = Path(os.environ.get("XDG_RUNTIME_DIR", tempfile.gettempdir())) / f"studio-controls-{os.getuid()}"
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_uid != os.getuid() or directory.stat().st_mode & 0o077:
        raise ControlError("Unsafe runtime directory")
    identity = device.get("path", device.get("url"))
    name = hashlib.sha256(identity.encode()).hexdigest() + ".lock"
    fd = os.open(directory / name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        deadline = time.monotonic() + TIMEOUT
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ControlError("Device busy; try again")
                time.sleep(0.02)
        yield
    finally:
        os.close(fd)


def allowed(meta, value):
    if meta["kind"] == "menu":
        return value in [o["value"] for o in meta["options"]]
    return meta["min"] <= value <= meta["max"] and (value - meta["min"]) % meta["step"] == 0


def formatted(control, value):
    if control.get("display") == "exposure100us" and value > 0:
        return f"{value / 10:g} ms · 1/{10000 / value:.1f} s"
    return f"{value}{(' ' + control['unit']) if control.get('unit') else ''}"


class Controller:
    def __init__(self, config):
        self.config = validate(config)
        self.devices = {d["id"]: d for d in config["devices"]}
        self.controls = {c["id"]: c for c in config["controls"]}
        self.actions = {a["id"]: a for a in config["actions"]}

    def row(self, control, all_meta):
        meta = all_meta.get(control["device"], {}).get(control["control"])
        base = {"id": control["id"], "label": control.get("label", control["id"]), "group": control.get("group", ""),
                "display": control.get("display", "raw"), "unit": control.get("unit", ""), "slider": control.get("slider", "linear")}
        if not meta:
            return {**base, "enabled": False, "error": "Unavailable", "kind": "unavailable", "text": "Unavailable"}
        enabled = not set(meta["flags"]) & {"inactive", "disabled", "read-only", "grabbed"}
        relation = control.get("enabledWhen")
        if relation:
            other = self.controls[relation["control"]]
            value = all_meta.get(other["device"], {}).get(other["control"], {}).get("value")
            enabled = enabled and value == relation["equals"]
        step = control.get("step", meta["step"])
        error = ""
        if step % meta["step"] != 0:
            error = "Configured step is not a multiple of device step"
        if control.get("slider") == "log" and meta["min"] <= 0:
            error = "Logarithmic slider requires positive range"
        if "default" in control and not allowed(meta, control["default"]):
            error = "Configured default is outside device values"
        if "toggleValues" in control and not all(allowed(meta, v) for v in control["toggleValues"]):
            error = "Configured toggle values are unsupported"
        text = formatted(control, meta["value"])
        if meta["kind"] == "menu":
            text = next((o["label"] for o in meta["options"] if o["value"] == meta["value"]), str(meta["value"]))
        if meta["kind"] == "bool":
            text = "On" if meta["value"] else "Off"
        return {**base, **meta, "enabled": bool(enabled and not error), "error": error, "uiStep": step, "text": text,
                "hasDefault": "default" in control, "toggleValues": control.get("toggleValues")}

    def snapshot(self):
        values, errors = {}, {}
        for name, device in self.devices.items():
            try:
                with device_lock(device):
                    values[name] = discover(device)
            except (ControlError, OSError) as error:
                values[name] = {}
                errors[name] = str(error)
        return {"controls": [self.row(c, values) for c in self.controls.values()], "errors": errors}

    def operate(self, control_id, operation, value=None):
        if control_id not in self.controls:
            raise ControlError("Unknown configured control")
        control = self.controls[control_id]
        device = self.devices[control["device"]]
        with device_lock(device):
            all_meta = {control["device"]: discover(device)}
            relation = control.get("enabledWhen")
            if relation:
                other = self.controls[relation["control"]]
                if other["device"] != control["device"]:
                    raise ControlError("Cross-device automatic dependencies are unsupported")
            row = self.row(control, all_meta)
            if not row["enabled"]:
                raise ControlError(row.get("error") or "Control is disabled by camera automatic mode or read-only state")
            if operation == "toggle":
                values = control.get("toggleValues", [0, 1] if row["kind"] == "bool" else [])
                if len(values) != 2 or row["value"] not in values:
                    raise ControlError("Control has no valid configured toggle")
                wanted = values[1] if row["value"] == values[0] else values[0]
            elif operation == "reset":
                if "default" not in control:
                    raise ControlError("No explicit reset value configured")
                wanted = control["default"]
            elif operation == "adjust":
                if row["kind"] != "int":
                    raise ControlError("Adjust requires an integer control")
                delta = integer(value)
                if delta % row["step"]:
                    raise ControlError("Adjustment is not a multiple of device step")
                wanted = row["value"] + delta
                wanted = min(row["max"], max(row["min"], wanted))
                wanted = row["min"] + ((wanted - row["min"]) // row["step"]) * row["step"]
            elif operation == "set":
                wanted = integer(value)
            else:
                raise ControlError("Unsupported operation")
            if not allowed(row, wanted):
                raise ControlError("Value outside supported range, step or menu")
            if device["type"] == "v4l2":
                v4l2(device, "--set-ctrl", f"{control['control']}={wanted}")
            else:
                field = {"power": "on", "brightness": "brightness", "temperature": "temperature"}[control["control"]]
                payload = {field: round(1000000 / wanted) if field == "temperature" else wanted}
                if control.get("powerOnChange"):
                    payload["on"] = 1
                light_request(device, payload)
            # Always read hardware state back; never declare requested values authoritative.
            return self.row(control, {control["device"]: discover(device)})

    def invoke(self, action_id):
        action = self.actions.get(action_id)
        if action is None:
            raise ControlError("Unknown configured action")
        return self.operate(action["control"], action["operation"], action.get("value"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--config")
    source.add_argument("--config-json")
    parser.add_argument("command", choices=("status", "label", "invoke", "set", "adjust", "reset"))
    parser.add_argument("arguments", nargs="*")
    args = parser.parse_args()
    try:
        if args.config:
            with open(args.config) as handle:
                raw = handle.read(LIMIT + 1)
        else:
            raw = args.config_json
        if len(raw) > LIMIT:
            raise ControlError("Configuration too large")
        controller = Controller(json.loads(raw))
        expected = {"status": 0, "label": 1, "invoke": 1, "reset": 1, "set": 2, "adjust": 2}[args.command]
        if len(args.arguments) != expected:
            raise ControlError("Incorrect command arguments")
        if args.command == "invoke":
            controller.invoke(args.arguments[0])
        elif args.command in ("set", "adjust"):
            controller.operate(args.arguments[0], args.command, int(args.arguments[1]))
        elif args.command == "reset":
            controller.operate(args.arguments[0], "reset")
        snapshot = controller.snapshot()
        if args.command == "label":
            row = next((r for r in snapshot["controls"] if r["id"] == args.arguments[0]), None)
            if row is None:
                raise ControlError("Unknown configured control")
            print(f"{row['label']}\n{row['text']}" + ("\nUnavailable" if row.get("error") and row["kind"] != "unavailable" else ""))
        else:
            print(json.dumps(snapshot))
        return 0
    except (ControlError, OSError, ValueError, TypeError) as error:
        if args.command == "label":
            print("Studio Controls\nUnavailable")
        else:
            print(json.dumps({"controls": [], "errors": {"request": str(error)}}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
