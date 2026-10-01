import copy
import unittest
from agent import key_code
from local_loop import execute_actions, run_route, local_match, validate_actions


class Target:
    def __init__(self):
        self.calls = []
        self.size = (854, 480)

    def focus(self): self.calls.append("focus")
    def release_all(self): self.calls.append("release")
    def wait_focused(self, seconds): self.calls.append("wait")
    def screenshot(self, width):
        self.calls.append("capture")
        return {"width": width, "height": 480, "source_width": self.size[0], "source_height": self.size[1], "png_base64": "fixture"}


SCREEN = {"description": "Title menu", "all": ["Play", "Settings"], "regions": [[0, 0, 500, 100]]}
PLAN = {"width": 854, "height": 480, "start": SCREEN, "steps": [
    {"action": {"cmd": "key", "key": "enter"}, "after": SCREEN, "settle_ms": 0},
    {"action": {"cmd": "key", "key": "escape"}, "after": SCREEN, "settle_ms": 0},
]}


class LoopTests(unittest.TestCase):
    def test_invalid_late_action_is_rejected_before_any_input(self):
        t = Target()
        with self.assertRaises(ValueError):
            execute_actions(t, [{"cmd": "key", "key": "w"}, {"cmd": "key", "key": "typo"}], lambda a: t.calls.append("input"), key_code)
        self.assertEqual(t.calls, [])

    def test_batch_returns_one_final_frame_and_releases_inputs(self):
        t = Target()
        actions = [{"cmd": "key", "key": "w", "action": "press"}, {"cmd": "wait", "ms": 100}]
        result = execute_actions(t, actions, lambda a: t.calls.append("input"), key_code)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(t.calls, ["focus", "input", "wait", "release", "capture"])

    def test_batch_failure_stops_without_retry_and_releases(self):
        t = Target()
        def failed(a):
            t.calls.append("input")
            raise RuntimeError("focus lost")
        result = execute_actions(t, [{"cmd": "key", "key": "w"}] * 2, failed, key_code, capture=False)
        self.assertEqual(result["completed"], 0)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(t.calls, ["focus", "input", "release"])

    def test_budget_is_checked_before_execution(self):
        with self.assertRaisesRegex(ValueError, "15 seconds"):
            validate_actions([{"cmd": "wait", "ms": 5000}] * 4, key_code)

    def test_unknown_start_screen_sends_no_input(self):
        t = Target()
        result = run_route(t, PLAN, lambda a: t.calls.append("input"), key_code, lambda *args: "Unexpected modal")
        self.assertEqual(result["status"], "fallback")
        self.assertNotIn("input", t.calls)

    def test_known_route_never_calls_jev(self):
        t = Target()
        def judge(*args): raise AssertionError("Local match must not call Jev")
        result = run_route(t, PLAN, lambda a: t.calls.append("input"), key_code, lambda *args: "Play Settings", "hybrid", judge)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(t.calls.count("input"), 2)
        self.assertEqual(t.calls.count("capture"), 3)

    def test_uncertain_jev_stops_before_input(self):
        t = Target()
        result = run_route(t, PLAN, lambda a: t.calls.append("input"), key_code, lambda *args: "Unknown", "hybrid", lambda *args: {"match": False})
        self.assertEqual(result["status"], "fallback")
        self.assertNotIn("input", t.calls)

    def test_changed_state_stops_remaining_actions(self):
        t = Target()
        observations = iter(["Play Settings", "Loading"])
        result = run_route(t, PLAN, lambda a: t.calls.append("input"), key_code, lambda *args: next(observations))
        self.assertEqual(result["status"], "fallback")
        self.assertEqual(result["completed"], 0)
        self.assertEqual(t.calls.count("input"), 1)

    def test_resize_aborts_route(self):
        t = Target()
        def resize(a): t.size = (900, 480)
        result = run_route(t, PLAN, resize, key_code, lambda *args: "Play Settings")
        self.assertIn("dimensions changed", result["error"])

    def test_bad_crop_is_rejected_before_focus(self):
        t, plan = Target(), copy.deepcopy(PLAN)
        plan["start"]["regions"] = [[0, 0, 9999, 20]]
        with self.assertRaises(ValueError):
            run_route(t, plan, lambda a: None, key_code, lambda *args: "Play Settings")
        self.assertEqual(t.calls, [])

    def test_literal_labels_require_every_clause(self):
        self.assertTrue(local_match("Servers CREATE NEW WORID", {"all": ["servers", "create new world|create new worid"]}))
        self.assertFalse(local_match("Settings", SCREEN))


if __name__ == "__main__":
    unittest.main()
