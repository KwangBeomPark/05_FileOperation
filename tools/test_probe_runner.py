import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from src.core import probe_runner
from src.core.probe_runner import run_probe


class ProbeRunnerTests(unittest.TestCase):
    def test_failed_result_pipe_is_closed_without_exposing_error(self):
        sender = Mock()
        sender.send.side_effect = OSError("sensitive path")
        with (
            patch.object(probe_runner, "_run_registered_probe", side_effect=RuntimeError("private")),
            self.assertLogs(probe_runner.logger, level="WARNING") as logs,
        ):
            probe_runner._worker_entry("probe", {}, sender)
        sender.close.assert_called_once()
        self.assertNotIn("sensitive path", " ".join(logs.output))
        self.assertNotIn("private", " ".join(logs.output))

    def test_taskkill_failure_falls_back_to_process_termination(self):
        process = Mock(pid=123)
        process.is_alive.side_effect = [True, True, False]
        with (
            patch.object(probe_runner.sys, "platform", "win32"),
            patch.object(probe_runner.subprocess, "run", side_effect=OSError("private")),
            self.assertLogs(probe_runner.logger, level="WARNING") as logs,
        ):
            probe_runner._terminate_process_tree(process)
        process.terminate.assert_called_once()
        self.assertNotIn("private", " ".join(logs.output))

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
