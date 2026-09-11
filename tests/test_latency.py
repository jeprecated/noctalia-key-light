"""CLI request-count and device-isolation regressions; no network/device I/O."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from test_backend import ROOT, b, config


class LatencyTests(unittest.TestCase):
    def setUp(self):
        self.cfg = config()
        self.cfg["devices"].append({"id": "light", "type": "key-light", "url": "http://127.0.0.1:1/elgato/lights"})
        self.cfg["controls"].append({"id": "brightness", "device": "light", "control": "brightness"})
        self.cfg["actions"].append({"id": "lightUp", "control": "brightness", "operation": "adjust", "value": 5})
        self.calls = []
        self.camera = (ROOT / "tests/camera.txt").read_text()

    def light(self, device, values=None):
        self.calls.append("GET" if values is None else "PUT")
        return {"on": 1, "brightness": 55, "temperature": 250}

    def v4l2(self, device, *args):
        self.calls.append(args[0])
        return self.camera if args[0] == "--list-ctrls-menus" else ""

    def cli(self, *argv, light=None):
        with tempfile.TemporaryDirectory() as runtime, patch.dict(os.environ, {"XDG_RUNTIME_DIR": runtime}), \
             patch.object(b, "light_request", side_effect=light or self.light), \
             patch.object(b, "v4l2", side_effect=self.v4l2), \
             patch("sys.argv", ["backend", "--config-json", json.dumps(self.cfg), *argv]), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            code = b.main()
        return code, out.getvalue()

    def test_camera_action_does_not_wait_for_light_and_reuses_readback(self):
        code, raw = self.cli("--device", "camera", "invoke", "zoomIn", light=AssertionError("must not contact light"))
        self.assertEqual(code, 0)
        self.assertEqual(self.calls, ["--list-ctrls-menus", "--set-ctrl", "--list-ctrls-menus"])
        self.assertNotIn("brightness", [r["id"] for r in json.loads(raw)["controls"]])

    def test_light_action_never_reads_camera_and_has_only_three_requests(self):
        code, raw = self.cli("--device", "light", "invoke", "lightUp")
        self.assertEqual(code, 0)
        self.assertEqual(self.calls, ["GET", "PUT", "GET"])
        self.assertEqual([r["id"] for r in json.loads(raw)["controls"]], ["brightness"])

    def test_camera_label_never_contacts_light(self):
        code, raw = self.cli("label", "af", light=AssertionError("must not contact light"))
        self.assertEqual(code, 0)
        self.assertEqual(self.calls, ["--list-ctrls-menus"])
        self.assertIn("On", raw)

    def test_camera_status_never_contacts_light(self):
        code, raw = self.cli("--device", "camera", "status", light=AssertionError("must not contact light"))
        self.assertEqual(code, 0)
        self.assertEqual(self.calls, ["--list-ctrls-menus"])
        self.assertFalse(json.loads(raw)["errors"])

    def test_failed_camera_operation_preserves_camera_snapshot_without_light(self):
        code, raw = self.cli("--device", "camera", "set", "auto", "2", light=AssertionError("must not contact light"))
        self.assertEqual(code, 1)
        result = json.loads(raw)
        self.assertTrue(result["controls"])
        self.assertTrue(result["errors"]["request"])
        self.assertTrue(all(call == "--list-ctrls-menus" for call in self.calls))

    def test_wrong_scope_and_unknown_device_never_write(self):
        for args in [("--device", "missing", "status"), ("--device", "camera", "invoke", "lightUp")]:
            with self.subTest(args=args):
                self.calls.clear()
                code, _ = self.cli(*args)
                self.assertEqual(code, 1)
                self.assertNotIn("PUT", self.calls)
                self.assertNotIn("--set-ctrl", self.calls)
                self.assertNotIn("GET", self.calls)

    def test_full_status_still_reads_both_devices(self):
        code, raw = self.cli("status")
        self.assertEqual(code, 0)
        self.assertEqual(self.calls, ["--list-ctrls-menus", "GET"])
        self.assertEqual(len(json.loads(raw)["controls"]), len(self.cfg["controls"]))


if __name__ == "__main__":
    unittest.main()
