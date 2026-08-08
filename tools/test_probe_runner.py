import tempfile
import threading
import unittest

from src.core.probe_runner import run_probe


class ProbeRunnerTests(unittest.TestCase):
    def test_allow_listed_path_probe_returns_serializable_result(self):
        with tempfile.TemporaryDirectory() as folder:
            result = run_probe(
                "path_access",
                {"read_folders": [folder], "write_folders": [folder]},
                timeout_seconds=3,
            )

        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.value["checked_count"], 1)
        self.assertEqual(result.value["failures"], [])

    def test_timeout_terminates_probe(self):
        result = run_probe("test_sleep", {"seconds": 5}, timeout_seconds=0.1)

        self.assertFalse(result.ok)
        self.assertTrue(result.timed_out)
        self.assertLess(result.elapsed_seconds, 2)

    def test_pre_cancelled_probe_is_terminated(self):
        cancelled = threading.Event()
        cancelled.set()

        result = run_probe(
            "test_sleep",
            {"seconds": 5},
            timeout_seconds=3,
            cancel_event=cancelled,
        )

        self.assertFalse(result.ok)
        self.assertTrue(result.cancelled)

    def test_unknown_probe_is_rejected_inside_worker(self):
        result = run_probe("not_allowed", {}, timeout_seconds=3)

        self.assertFalse(result.ok)
        self.assertIn("Unsupported probe", result.error)


if __name__ == "__main__":
    unittest.main()
