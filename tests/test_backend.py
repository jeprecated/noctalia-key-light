import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("backend", ROOT / "studio-controls/backend.py")
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
FIXTURE = (ROOT / "tests/camera.txt").read_text()


def config():
    return {"devices": [{"id": "camera", "type": "v4l2", "path": "/dev/synthetic-studio-camera"}], "controls": [
        {"id": "auto", "device": "camera", "control": "auto_exposure", "toggleValues": [1, 3]},
        {"id": "exposure", "device": "camera", "control": "exposure_time_absolute", "step": 10, "display": "exposure100us", "slider": "log", "default": 166, "enabledWhen": {"control": "auto", "equals": 1}},
        {"id": "pan", "device": "camera", "control": "pan_absolute", "step": 3600},
        {"id": "zoom", "device": "camera", "control": "zoom_absolute"},
        {"id": "af", "device": "camera", "control": "focus_automatic_continuous"},
        {"id": "focus", "device": "camera", "control": "focus_absolute"},
        {"id": "frequency", "device": "camera", "control": "power_line_frequency"},
    ], "actions": [{"id": "autoToggle", "control": "auto", "operation": "toggle"}, {"id": "zoomIn", "control": "zoom", "operation": "adjust", "value": 1}]}


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = self.root / "state.json"
        self.state.write_text("{}")
        self.writes = self.root / "writes"
        self.env = patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(self.root), "V4L2_CTL": str(ROOT / "tests/fake-v4l2.py"), "FAKE_CAMERA_STATE": str(self.state), "FAKE_CAMERA_WRITES": str(self.writes)})
        self.env.start()
        self.controller = b.Controller(config())

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_all_seventeen_controls_and_sparse_menus(self):
        controls = b.parse_controls(FIXTURE)
        self.assertEqual(len(controls), 17)
        self.assertEqual([x["value"] for x in controls["auto_exposure"]["options"]], [1, 3])
        self.assertEqual(controls["pan_absolute"]["step"], 3600)
        self.assertEqual(controls["focus_absolute"]["step"], 5)
        self.assertEqual(controls["focus_automatic_continuous"]["kind"], "bool")

    def test_empty_config_does_not_contact_devices(self):
        with patch.object(b, "discover", side_effect=AssertionError("unexpected device")):
            self.assertEqual(b.Controller({}).snapshot(), {"controls": [], "errors": {}})

    def test_snapshot_does_not_apply_default(self):
        snapshot = self.controller.snapshot()
        exposure = snapshot["controls"][1]
        self.assertFalse(exposure["enabled"])
        self.assertEqual(exposure["value"], 299)
        self.assertIn("29.9 ms", exposure["text"])
        self.assertFalse(self.writes.exists())

    def test_auto_mode_then_manual_and_explicit_reset(self):
        with self.assertRaises(b.ControlError):
            self.controller.operate("exposure", "set", 166)
        self.controller.invoke("autoToggle")
        self.assertEqual(json.loads(self.state.read_text()), {"auto_exposure": 1})
        self.assertTrue(self.controller.snapshot()["controls"][1]["enabled"])
        self.controller.operate("exposure", "reset")
        self.assertEqual(json.loads(self.state.read_text())["exposure_time_absolute"], 166)
        self.controller.invoke("autoToggle")
        self.assertFalse(self.controller.snapshot()["controls"][1]["enabled"])

    def test_sparse_menu_rejects_holes_and_invalid_values(self):
        for value in (0, 2, 4, -1):
            with self.assertRaises(b.ControlError):
                self.controller.operate("auto", "set", value)
        self.assertFalse(self.writes.exists())

    def test_device_step_and_clamp(self):
        with self.assertRaises(b.ControlError):
            self.controller.operate("pan", "set", 1)
        with self.assertRaises(b.ControlError):
            self.controller.operate("pan", "adjust", 1)
        self.controller.operate("pan", "adjust", -72000)
        self.assertEqual(json.loads(self.state.read_text())["pan_absolute"], -36000)
        self.controller.operate("pan", "adjust", 108000)
        self.assertEqual(json.loads(self.state.read_text())["pan_absolute"], 36000)

    def test_focus_inactive_then_step(self):
        with self.assertRaises(b.ControlError):
            self.controller.operate("focus", "set", 45)
        self.controller.operate("af", "toggle")
        self.controller.operate("focus", "set", 45)
        with self.assertRaises(b.ControlError):
            self.controller.operate("focus", "set", 46)

    def test_misconfigured_default_step_and_toggle_fail_closed(self):
        for field, value in (("step", 1), ("default", 1), ("toggleValues", [0, 1])):
            cfg = config()
            cfg["controls"][2][field] = value
            ctl = b.Controller(cfg)
            row = ctl.snapshot()["controls"][2]
            self.assertFalse(row["enabled"])
            self.assertTrue(row["error"])
            with self.assertRaises(b.ControlError):
                ctl.operate("pan", "adjust", 3600)
        self.assertFalse(self.writes.exists())

    def test_no_unconfigured_actions_controls_or_reset(self):
        for call in (lambda: self.controller.invoke("surprise"), lambda: self.controller.operate("gain", "set", 2), lambda: self.controller.operate("zoom", "reset")):
            with self.assertRaises(b.ControlError):
                call()
        self.assertFalse(self.writes.exists())

    def test_readonly_and_grabbed_controls_rejected(self):
        for flag in ("read-only", "grabbed", "disabled"):
            with patch.object(b, "discover", return_value={"zoom_absolute": {"kind": "int", "min": 100, "max": 500, "step": 1, "value": 100, "flags": [flag], "options": []}}):
                with self.assertRaises(b.ControlError):
                    self.controller.operate("zoom", "adjust", 1)
        self.assertFalse(self.writes.exists())

    def test_concurrent_process_adjustments_are_not_lost(self):
        cfg = self.root / "config.json"
        cfg.write_text(json.dumps(config()))
        processes = [subprocess.Popen([sys.executable, str(ROOT / "studio-controls/backend.py"), "--config", str(cfg), "invoke", "zoomIn"], stdout=subprocess.PIPE) for _ in range(8)]
        for process in processes:
            output, _ = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, output)
        self.assertEqual(json.loads(self.state.read_text())["zoom_absolute"], 108)
        self.assertEqual(len(self.writes.read_text().splitlines()), 8)

    def test_disconnect_reconnect_and_timeout_never_write(self):
        for variable in ("FAKE_CAMERA_OFFLINE", "FAKE_CAMERA_TIMEOUT"):
            with patch.dict(os.environ, {variable: "1"}):
                snapshot = self.controller.snapshot()
                self.assertTrue(snapshot["errors"])
                self.assertTrue(all(not r["enabled"] for r in snapshot["controls"]))
        self.assertFalse(self.writes.exists())
        self.assertFalse(self.controller.snapshot()["errors"])
        self.assertFalse(self.writes.exists())

    def test_invalid_config_rejected_before_io(self):
        for update in ({"path": "0"}, {"path": "/dev/camera\x00oops"}, {"type": "shell"}):
            cfg = config()
            cfg["devices"][0].update(update)
            with self.assertRaises(b.ControlError):
                b.Controller(cfg)
        for value in (True, float("nan"), 1.5, -1):
            cfg = config()
            cfg["controls"][0]["step"] = value
            with self.assertRaises(b.ControlError):
                b.Controller(cfg)

    def test_shell_metacharacters_are_never_interpreted(self):
        cfg = config()
        cfg["devices"][0]["path"] = "/dev/synthetic;touch SHOUND_NOT_EXIST"
        self.assertFalse(b.Controller(cfg).snapshot()["errors"])
        self.assertFalse(Path("SHOUND_NOT_EXIST").exists())

    def test_label_is_readonly_and_show_actual_menu_state(self):
        result = subprocess.run([sys.executable, str(ROOT / "studio-controls/backend.py"), "--config-json", json.dumps(config()), "label", "auto"], capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout, "auto\nAperture Priority Mode\n")
        self.assertFalse(self.writes.exists())


if __name__ == "__main__":
    unittest.main()
