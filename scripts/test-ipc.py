#!/usr/bin/env python3
"""Exercise real Quickshell IPC with an isolated shell and loopback fake light."""
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


requests = queue.Queue()
light = {"on": 0, "brightness": 25, "temperature": 222}


class LightHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.respond()

    def do_PUT(self):
        assert self.path == "/elgato/lights"
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert body["numberOfLights"] == 1
        light.update(body["lights"][0])
        self.respond()
        requests.put(body["lights"][0])

    def respond(self):
        body = json.dumps({"numberOfLights": 1, "lights": [light]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


server = HTTPServer(("127.0.0.1", 0), LightHandler)
threading.Thread(target=server.serve_forever, daemon=True).start()
try:
    with tempfile.TemporaryDirectory(prefix="key-light-ipc-") as directory:
        root = Path(directory)
        shutil.copytree(Path(__file__).resolve().parents[1] / "key-light", root / "plugin")
        shell = root / "shell.qml"
        shell.write_text('''import QtQuick
import Quickshell
import Quickshell.Io
import "plugin" as Plugin

ShellRoot {
  id: root
  property var api: QtObject {
    property var pluginSettings: ({host: "127.0.0.1", port: PORT, pollIntervalMs: 60000})
    property var mainInstance: main
  }
  Plugin.Main { id: main; pluginApi: root.api }
  Component { id: widget; Plugin.BarWidget { pluginApi: root.api } }
  property var first: null
  property var second: null
  Connections {
    target: main.store
    function onOnlineChanged() { if (main.store.online) console.log("TEST_READY") }
    function onOnChanged() { console.log("TEST_POWER " + main.store.on) }
  }
  IpcHandler {
    target: "test"
    function widgets(): string {
      root.first = widget.createObject(root)
      root.second = widget.createObject(root)
      return JSON.stringify([root.first.store === main.store, root.second.store === main.store])
    }
    function state(): string {
      return JSON.stringify([main.store.on, root.first.store.on, root.second.store.on])
    }
  }
}
'''.replace("PORT", str(server.server_port)))
        for name in ("runtime", "cache", "config"):
            (root / name).mkdir(mode=0o700)
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QML_DISABLE_DISK_CACHE="1",
                   XDG_RUNTIME_DIR=str(root / "runtime"), XDG_CACHE_HOME=str(root / "cache"),
                   XDG_CONFIG_HOME=str(root / "config"))
        command = ["quickshell", "-p", str(shell)]
        with (root / "shell.log").open("w+") as log:
            process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True)
            lines = queue.Queue()

            def read_output():
                for line in process.stdout:
                    log.write(line)
                    log.flush()
                    lines.put(line)

            threading.Thread(target=read_output, daemon=True).start()

            def wait_for(marker):
                while marker not in lines.get(timeout=10):
                    pass

            def ipc(target, method):
                return subprocess.check_output(command + ["ipc", "call", target, method],
                                               env=env, text=True, timeout=10).strip()

            try:
                wait_for("TEST_READY")
                # No bar widget is instantiated: Main must own the IPC and store.
                ipc("plugin:key-light", "toggle")
                assert requests.get(timeout=10) == {"on": 1}
                wait_for("TEST_POWER true")
                assert json.loads(ipc("test", "widgets")) == [True, True]
                ipc("plugin:key-light", "toggle")
                assert requests.get(timeout=10) == {"on": 0}
                wait_for("TEST_POWER false")
                assert json.loads(ipc("test", "state")) == [False, False, False]
            finally:
                process.terminate()
                process.wait(timeout=10)
                process.stdout.close()
                log.seek(0)
                output = log.read()
                print(output)
            assert "ReferenceError" not in output and "TypeError" not in output
finally:
    server.shutdown()
    server.server_close()

print("IPC toggle and shared widget state passed (fake light only)")
