#!/usr/bin/env python3
"""Real offscreen Quickshell, popup widgets and IPC; fake V4L2 and loopback light only."""
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch
from test_backend import ROOT, b, config

requests = []
light = {"on": 0, "brightness": 25, "temperature": 222}
light_blocked = threading.Event()
light_started = threading.Event()
light_release = threading.Event()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if light_blocked.is_set():
            light_started.set()
            light_release.wait(timeout=5)
        self.respond()

    def do_PUT(self):
        values = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["lights"][0]
        requests.append(values)
        light.update(values)
        self.respond()

    def respond(self):
        assert self.path == "/elgato/lights"
        raw = json.dumps({"numberOfLights": 1, "lights": [light]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_args):
        pass


def run():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix="studio-controls-qml-") as temp:
            directory = Path(temp)
            shutil.copytree(ROOT / "studio-controls", directory / "plugin")
            for name in ("runtime", "cache", "config"):
                (directory / name).mkdir(mode=0o700)
            state = directory / "state.json"
            state.write_text("{}")
            writes = directory / "writes"
            cfg = config()
            present = {c["control"] for c in cfg["controls"]}
            for name in b.parse_controls((ROOT / "tests/camera.txt").read_text()):
                if name not in present:
                    cfg["controls"].append({"id": name, "device": "camera", "control": name, "group": "Other"})
            cfg["devices"].append({"id": "light", "type": "key-light", "url": f"http://127.0.0.1:{server.server_port}/elgato/lights"})
            cfg["controls"] += [{"id": "power", "device": "light", "control": "power"}, {"id": "lightBrightness", "device": "light", "control": "brightness", "step": 5, "powerOnChange": True}, {"id": "lightTemperature", "device": "light", "control": "temperature", "step": 100, "unit": "K", "default": 3200}]
            cfg["actions"] += [{"id": "lightToggle", "control": "power", "operation": "toggle"}, {"id": "lightUp", "control": "lightBrightness", "operation": "adjust", "value": 5}, {"id": "lightDown", "control": "lightBrightness", "operation": "adjust", "value": -5}]
            cfg["actions"] += [{"id": "lightWarm", "label": "Warm 3200 K", "control": "lightTemperature", "operation": "set", "value": 3200}, {"id": "blankLabel", "label": " \t", "control": "power", "operation": "toggle"}]
            cfg["backendCommand"] = [sys.executable, str(directory / "plugin/backend.py")]
            cfg["pollIntervalMs"] = 60000
            shell = directory / "shell.qml"
            shell.write_text('''import QtQuick
import Quickshell
import Quickshell.Io
import "plugin" as Plugin
ShellRoot {
  id: root
  property var api: QtObject { property var pluginSettings: SETTINGS; property var mainInstance: main }
  Plugin.Main { id: main; pluginApi: root.api }
  FloatingWindow { id: anchorWindow; implicitWidth: 100; implicitHeight: 50; Plugin.BarWidget { id: widget; pluginApi: root.api } }
  Plugin.StudioPopup { id: popup; store: main.store; anchorItem: widget }
  Item { id: rowHost; parent: anchorWindow.contentItem; visible: false }
  property var rows: []
  Component { id: rowComponent; Plugin.ControlRow { width: 400; store: main.store } }
  function find(item, name) {
    if (item.objectName === name) return item
    for (const child of item.children ?? []) { const found = find(child, name); if (found) return found }
    return null
  }
  IpcHandler {
    target: "test"
    function state(): string { return JSON.stringify({controls: main.controls, errors: main.errors, busy: main.busy, pending: main.pending.length}) }
    function open(): void { popup.open = true }
    function close(): void { popup.open = false }
    function rows(): int {
      for (const row of root.rows) row.destroy()
      root.rows = []
      for (const control of main.controls) root.rows.push(rowComponent.createObject(rowHost, {control: control}))
      return root.rows.length
    }
    function activate(name: string, value: string): bool {
      for (const row of root.rows) {
        const item = root.find(row, name)
        if (!item) continue
        if (!item.enabled) return false
        if (name.startsWith("switch-")) { item.checked = value === "1"; item.toggled() }
        else if (name.startsWith("menu-")) { item.currentIndex = Number(value); item.activated(Number(value)) }
        else if (name.startsWith("slider-")) { item.value = Number(value); item.moved() }
        else item.clicked()
        return true
      }
      return false
    }
    function action(name: string, click: bool): bool {
      const button = root.find(popup.contentItem, "action-" + name)
      if (!button) return false
      if (click) button.clicked()
      return true
    }
    function cameraPath(mode: string): void {
      const settings = JSON.parse(JSON.stringify(root.api.pluginSettings))
      if (mode === "missing") delete settings.devices[0].path
      else settings.devices[0].path = mode === "null" ? null : (mode === "empty" ? "" : CAMERA_PATH)
      root.api.pluginSettings = settings
      main.refresh()
    }
    function burst(): void { for (let i = 0; i < 40; i++) main.invoke("zoomIn") }
    function invalidBurst(): void { main.adjustValue("pan", 1800); main.adjustValue("pan", 1800) }
    function lightBurst(): void {
      for (let i = 0; i < 20; i++) main.invoke("lightUp")
      main.invoke("lightDown")
      main.invoke("lightToggle")
      main.invoke("lightToggle")
    }
    function shared(): bool { return widget.store === main.store }
    function brokenHelper(): void { root.api.pluginSettings = Object.assign({}, root.api.pluginSettings, {backendCommand: ["/no/such/studio-controls-helper"]}); main.refresh() }
    function healthyHelper(): void { root.api.pluginSettings = Object.assign({}, root.api.pluginSettings, {backendCommand: GOOD_BACKEND}); main.refresh() }
  }
}
'''.replace("SETTINGS", "(" + json.dumps(cfg) + ")").replace("GOOD_BACKEND", json.dumps(cfg["backendCommand"])).replace("CAMERA_PATH", json.dumps(cfg["devices"][0]["path"])))
            env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QML_DISABLE_DISK_CACHE="1", XDG_RUNTIME_DIR=str(directory / "runtime"), XDG_CACHE_HOME=str(directory / "cache"), XDG_CONFIG_HOME=str(directory / "config"), V4L2_CTL=str(ROOT / "tests/fake-v4l2.py"), FAKE_CAMERA_STATE=str(state), FAKE_CAMERA_WRITES=str(writes))
            command = ["quickshell", "-p", str(shell)]
            with (directory / "shell.log").open("w+") as log:
                process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)
                def ipc(target, method, *args):
                    return subprocess.check_output(command + ["ipc", "call", target, method, *args], env=env, text=True, stderr=subprocess.DEVNULL, timeout=10).strip()
                def settled():
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        if process.poll() is not None:
                            raise AssertionError("Quickshell exited")
                        try:
                            snapshot = json.loads(ipc("test", "state"))
                            if not snapshot["busy"] and not snapshot["pending"] and snapshot["controls"]:
                                return snapshot
                        except subprocess.CalledProcessError:
                            pass
                        time.sleep(0.05)
                    raise AssertionError(f"Quickshell did not settle: {snapshot}")
                try:
                    snapshot = settled()
                    assert len(snapshot["controls"]) == 20
                    assert not snapshot["errors"]
                    assert ipc("test", "shared") == "true"
                    ipc("test", "open")
                    assert ipc("test", "rows") == "20"
                    time.sleep(0.3)
                    assert not writes.exists() and not requests, "Opening or binding controls wrote hardware"
                    assert ipc("test", "action", "lightWarm", "false") == "true"
                    assert ipc("test", "action", "lightToggle", "false") == "false"
                    assert ipc("test", "action", "blankLabel", "false") == "false"
                    for method, args in (("set", ("exposure", "166")), ("set", ("auto", "2")), ("invoke", ("unknown",))):
                        ipc("plugin:studio-controls", method, *args)
                        rejected = settled()
                        assert len(rejected["controls"]) == 20
                        assert rejected["errors"]["request"]
                        assert rejected["controls"][1]["value"] == 299
                        assert rejected["controls"][18]["value"] == 25
                        assert not writes.exists() and not requests
                    for mode in ("missing", "null", "empty"):
                        ipc("test", "cameraPath", mode)
                        unavailable = settled()
                        assert "unconfigured" in unavailable["errors"]["camera"]
                        assert len(unavailable["controls"]) == 20
                        assert all(row["kind"] == "unavailable" for row in unavailable["controls"][:17])
                        assert all(row["enabled"] for row in unavailable["controls"][17:])
                        assert ipc("test", "rows") == "20"
                        ipc("plugin:studio-controls", "set", "auto", "1")
                        assert settled()["errors"]["request"]
                        assert not writes.exists() and not requests
                    ipc("test", "cameraPath", "configured")
                    assert not settled()["errors"]
                    # A disconnected configured camera is different from missing configuration.
                    offline_state = state.with_suffix(".offline")
                    state.rename(offline_state)
                    ipc("plugin:studio-controls", "refresh")
                    assert settled()["controls"][0]["kind"] == "unavailable"
                    assert ipc("test", "rows") == "20"
                    offline_state.rename(state)
                    ipc("plugin:studio-controls", "refresh")
                    assert not settled()["errors"]
                    ipc("test", "rows")
                    assert not writes.exists() and not requests, "Reconnect wrote hardware"
                    assert ipc("test", "activate", "reset-exposure", "") == "false", "Inactive exposure reset enabled"
                    assert ipc("test", "activate", "switch-auto", "0") == "true"
                    snapshot = settled()
                    assert snapshot["controls"][0]["value"] == 1
                    assert snapshot["controls"][1]["enabled"]
                    ipc("test", "rows")
                    assert ipc("test", "activate", "reset-exposure", "") == "true"
                    settled()
                    assert json.loads(state.read_text())["exposure_time_absolute"] == 166
                    ipc("test", "rows")
                    assert ipc("test", "activate", "menu-frequency", "2") == "true"
                    settled()
                    assert json.loads(state.read_text())["power_line_frequency"] == 2
                    ipc("test", "rows")
                    assert ipc("test", "activate", "slider-exposure", str(math.log(250))) == "true"
                    settled()
                    assert json.loads(state.read_text())["exposure_time_absolute"] == 250
                    assert ipc("test", "activate", "slider-pan", "7200") == "true"
                    settled()
                    assert json.loads(state.read_text())["pan_absolute"] == 7200
                    # +/- must use fresh device state, not the stale test-row snapshot.
                    assert ipc("test", "activate", "increase-pan", "") == "true"
                    settled()
                    assert json.loads(state.read_text())["pan_absolute"] == 10800
                    for _ in range(5):
                        ipc("plugin:studio-controls", "invoke", "zoomIn")
                    settled()
                    assert json.loads(state.read_text())["zoom_absolute"] == 105
                    ipc("plugin:studio-controls", "invoke", "lightDown")
                    settled()
                    assert requests[-1] == {"brightness": 20, "on": 1}
                    assert light["temperature"] == 222
                    ipc("plugin:studio-controls", "invoke", "lightToggle")
                    settled()
                    assert requests[-1] == {"on": 0}
                    ipc("plugin:studio-controls", "invoke", "lightUp")
                    settled()
                    assert requests[-1] == {"brightness": 25, "on": 1}
                    assert light["temperature"] == 222
                    assert ipc("test", "action", "lightWarm", "true") == "true"
                    warm = settled()
                    assert requests[-1] == {"temperature": 312}
                    assert light["brightness"] == 25 and light["on"] == 1
                    assert warm["controls"][19]["value"] == round(1000000 / 312)
                    # Hold a real fake-light HTTP request open: camera IPC and
                    # readback must finish while the light worker is still busy.
                    light_blocked.set()
                    ipc("plugin:studio-controls", "invoke", "lightUp")
                    assert light_started.wait(timeout=2), "Fake light request did not start"
                    try:
                        started = time.monotonic()
                        ipc("plugin:studio-controls", "set", "zoom", "120")
                        deadline = started + 1.5
                        while time.monotonic() < deadline:
                            current = json.loads(ipc("test", "state"))
                            zoom = next(row for row in current["controls"] if row["id"] == "zoom")
                            if zoom.get("value") == 120:
                                break
                            time.sleep(0.02)
                        else:
                            raise AssertionError("Camera IPC waited for the blocked light")
                        assert current["busy"], "Light should still be blocked"
                        print(f"Camera write/readback while light blocked: {time.monotonic() - started:.3f}s")
                    finally:
                        light_blocked.clear()
                        light_release.set()
                    settled()
                    # The reverse direction also stays independent, including
                    # contention from another CLI process holding the camera lock.
                    with patch.dict(os.environ, {"XDG_RUNTIME_DIR": env["XDG_RUNTIME_DIR"]}), b.device_lock(cfg["devices"][0]):
                        ipc("plugin:studio-controls", "invoke", "zoomIn")
                        before_brightness = light["brightness"]
                        ipc("plugin:studio-controls", "invoke", "lightUp")
                        deadline = time.monotonic() + 1.5
                        while light["brightness"] == before_brightness and time.monotonic() < deadline:
                            time.sleep(0.02)
                        assert light["brightness"] == before_brightness + 5, "Light waited for camera lock"
                    settled()
                    before_writes = len(writes.read_text().splitlines())
                    ipc("test", "burst")
                    settled()
                    assert json.loads(state.read_text())["zoom_absolute"] == 161
                    burst_writes = len(writes.read_text().splitlines()) - before_writes
                    assert burst_writes <= 2, f"Dial burst produced {burst_writes} writes"
                    print(f"40 same-direction dial turns: {burst_writes} writes, exact final value")
                    before_writes = len(writes.read_text().splitlines())
                    ipc("test", "invalidBurst")
                    assert settled()["errors"]["request"]
                    assert len(writes.read_text().splitlines()) == before_writes, "Invalid steps were combined into a valid write"
                    before_requests = len(requests)
                    ipc("test", "lightBurst")
                    settled()
                    assert light["brightness"] == 95 and light["on"] == 1, "Direction reversal or toggle ordering lost"
                    assert len(requests) - before_requests <= 5
                    ipc("plugin:studio-controls", "refresh")
                    assert not settled()["errors"]
                    before = len(requests), len(writes.read_text().splitlines())
                    ipc("test", "close")
                    ipc("test", "open")
                    ipc("plugin:studio-controls", "refresh")
                    settled()
                    assert before == (len(requests), len(writes.read_text().splitlines()))
                    ipc("test", "brokenHelper")
                    time.sleep(0.5)
                    unavailable = json.loads(ipc("test", "state"))
                    assert unavailable["errors"] and not unavailable["controls"], unavailable
                    ipc("test", "healthyHelper")
                    assert not settled()["errors"]
                    assert before == (len(requests), len(writes.read_text().splitlines()))
                finally:
                    process.terminate()
                    process.wait(timeout=10)
                    log.seek(0)
                    output = log.read()
                    print(output)
                for error in ("ReferenceError", "TypeError", "Binding loop", "Unable to assign", "is not a type", "Cannot assign", "Error loading"):
                    assert error not in output, output
    finally:
        server.shutdown()
        server.server_close()
    print("Real QML popup/20 controls/shared state/IPC tests passed; fake devices only")


if __name__ == "__main__":
    run()
