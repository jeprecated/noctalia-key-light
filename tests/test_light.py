import copy
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch
from test_backend import ROOT, b, config


class LightTests(unittest.TestCase):
    def setUp(self):
        self.light = {"on": 0, "brightness": 25, "temperature": 222}
        self.writes = []
        self.mode = "normal"
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.respond()

            def do_PUT(self):
                values = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["lights"][0]
                owner.writes.append(values)
                owner.light.update(values)
                self.respond()

            def respond(self):
                if owner.mode == "redirect":
                    self.send_response(302)
                    self.send_header("Location", "http://example.invalid/should-never-connect")
                    self.end_headers()
                    return
                raw = json.dumps({"lights": [owner.light]}).encode()
                if owner.mode == "malformed":
                    raw = b"{}"
                if owner.mode == "oversized":
                    raw = b" " * (b.LIMIT + 1)
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                try:
                    if owner.mode == "drip":
                        for char in raw:
                            self.wfile.write(bytes([char]))
                            self.wfile.flush()
                            time.sleep(0.05)
                    else:
                        self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *_args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.temp.name})
        self.env.start()
        self.config = {"devices": [{"id": "light", "type": "key-light", "url": f"http://127.0.0.1:{self.server.server_port}/elgato/lights"}], "controls": [
            {"id": "power", "device": "light", "control": "power"},
            {"id": "brightness", "device": "light", "control": "brightness", "step": 5},
            {"id": "temperature", "device": "light", "control": "temperature", "step": 100, "default": 3200},
        ]}
        self.controller = b.Controller(self.config)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.env.stop()
        self.temp.cleanup()

    def test_unconfigured_camera_never_locks_or_invokes_v4l2_and_light_works(self):
        for path in ({}, {"path": None}, {"path": ""}):
            with self.subTest(path=path):
                cfg = copy.deepcopy(self.config)
                cfg["devices"].append({"id": "camera", "type": "v4l2", **path})
                cfg["controls"] += config()["controls"]
                ctl = b.Controller(cfg)
                with patch.object(b, "v4l2") as camera, patch.object(b, "device_lock", wraps=b.device_lock) as lock:
                    snapshot = ctl.snapshot()
                    self.assertIn("unconfigured", snapshot["errors"]["camera"])
                    self.assertTrue(all(row["enabled"] for row in snapshot["controls"][:3]))
                    self.assertTrue(all(row["kind"] == "unavailable" for row in snapshot["controls"][3:]))
                    with self.assertRaisesRegex(b.ControlError, "unconfigured"):
                        ctl.operate("auto", "set", 1)
                    with self.assertRaisesRegex(b.ControlError, "unconfigured"):
                        b.discover(cfg["devices"][1])
                    self.assertEqual(self.writes, [])
                    ctl.operate("brightness", "adjust", 5)
                    self.assertEqual(len(self.writes), 1)
                    self.assertEqual(self.light["temperature"], 222)
                    self.writes.clear()
                    camera.assert_not_called()
                    self.assertTrue(all(call.args[0]["id"] == "light" for call in lock.call_args_list))

    def test_cli_failed_operations_preserve_mixed_snapshot_without_writes(self):
        cfg = copy.deepcopy(self.config)
        cfg["devices"] += config()["devices"]
        cfg["controls"] += config()["controls"]
        state = Path(self.temp.name) / "camera.json"
        state.write_text("{}")
        writes = Path(self.temp.name) / "camera-writes"
        env = dict(os.environ, V4L2_CTL=str(ROOT / "tests/fake-v4l2.py"), FAKE_CAMERA_STATE=str(state), FAKE_CAMERA_WRITES=str(writes))
        for command in (["adjust", "exposure", "10"], ["set", "auto", "2"], ["invoke", "unknown"]):
            result = subprocess.run([sys.executable, str(ROOT / "studio-controls/backend.py"), "--config-json", json.dumps(cfg), *command], env=env, text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 1, result.stderr)
            snapshot = json.loads(result.stdout)
            self.assertTrue(snapshot["errors"]["request"])
            self.assertEqual(len(snapshot["controls"]), 10)
            self.assertEqual(snapshot["controls"][1]["value"], 25)
            self.assertEqual(snapshot["controls"][4]["value"], 299)
            self.assertEqual(self.writes, [])
            self.assertFalse(writes.exists())
        for path in ({}, {"path": None}, {"path": ""}):
            cfg["devices"][1] = {"id": "camera", "type": "v4l2", **path}
            for command in (["status"], ["set", "auto", "1"], ["adjust", "brightness", "0"]):
                result = subprocess.run([sys.executable, str(ROOT / "studio-controls/backend.py"), "--config-json", json.dumps(cfg), *command], env=env, text=True, capture_output=True, timeout=15)
                self.assertEqual(result.returncode, 1 if command[0] == "set" else 0, result.stderr)
                snapshot = json.loads(result.stdout)
                self.assertIn("unconfigured", snapshot["errors"]["camera"])
                self.assertEqual(len(snapshot["controls"]), 10)
                self.assertEqual(snapshot["controls"][1]["value"], 25)
                self.assertFalse(writes.exists())

    def test_readonly_does_not_apply_defaults(self):
        self.assertEqual(len(self.controller.snapshot()["controls"]), 3)
        self.assertEqual(self.writes, [])
        self.assertEqual(self.light["temperature"], 222)

    def test_brightness_preserves_power_without_explicit_policy(self):
        self.controller.operate("brightness", "adjust", 5)
        self.assertEqual(self.writes, [{"brightness": 30}])
        self.assertEqual(self.light["on"], 0)
        self.assertEqual(self.light["temperature"], 222)

    def test_explicit_power_on_both_brightness_directions(self):
        self.config["controls"][1]["powerOnChange"] = True
        self.controller.operate("brightness", "adjust", -5)
        self.assertEqual(self.writes[-1], {"brightness": 20, "on": 1})
        self.controller.operate("power", "toggle")
        self.controller.operate("brightness", "adjust", 5)
        self.assertEqual(self.writes[-1], {"brightness": 25, "on": 1})
        self.assertEqual(self.light["temperature"], 222)

    def test_kelvin_readback_is_device_actual_not_requested(self):
        row = self.controller.operate("temperature", "reset")
        self.assertEqual(self.writes[-1], {"temperature": 312})
        self.assertEqual(row["value"], round(1000000 / 312))
        self.assertNotEqual(row["value"], 3200)

    def test_range_clamp_and_invalid_set(self):
        self.controller.operate("brightness", "adjust", 500)
        self.assertEqual(self.light["brightness"], 100)
        for value in (-1, 101):
            with self.assertRaises(b.ControlError):
                self.controller.operate("brightness", "set", value)
        self.assertEqual(len(self.writes), 1)

    def test_malformed_oversized_redirect_fail_closed(self):
        for mode in ("malformed", "oversized", "redirect"):
            self.mode = mode
            snapshot = self.controller.snapshot()
            self.assertTrue(snapshot["errors"])
            self.assertTrue(all(not row["enabled"] for row in snapshot["controls"]))
        self.assertEqual(self.writes, [])

    def test_total_deadline_includes_slow_drip_response(self):
        self.mode = "drip"
        start = time.monotonic()
        with patch.object(b, "TIMEOUT", 0.2):
            self.assertTrue(self.controller.snapshot()["errors"])
        self.assertLess(time.monotonic() - start, 1)
        self.assertEqual(self.writes, [])

    def test_invalid_endpoint_or_power_policy(self):
        for url in ("https://light.example/", "http://user:password@light.example/", "ftp://light.example/"):
            self.config["devices"][0]["url"] = url
            with self.assertRaises(b.ControlError):
                b.Controller(self.config)


if __name__ == "__main__":
    unittest.main()
