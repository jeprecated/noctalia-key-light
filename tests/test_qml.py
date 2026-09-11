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
from test_backend import ROOT, b, config

requests = []
light = {"on": 0, "brightness": 25, "temperature": 222}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
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
    function shared(): bool { return widget.store === main.store }
    function brokenHelper(): void { root.api.pluginSettings = Object.assign({}, root.api.pluginSettings, {backendCommand: ["/no/such/studio-controls-helper"]}); main.refresh() }
    function healthyHelper(): void { root.api.pluginSettings = Object.assign({}, root.api.pluginSettings, {backendCommand: GOOD_BACKEND}); main.refresh() }
  }
}
'''.replace("SETTINGS", "(" + json.dumps(cfg) + ")").replace("GOOD_BACKEND", json.dumps(cfg["backendCommand"])))
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
