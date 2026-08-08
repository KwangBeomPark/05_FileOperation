import os
import threading
import unittest
import uuid


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication

from src.main import parse_startup_arguments
from src.ui.single_instance import SingleInstanceController


class SingleInstanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_tray_switch_is_removed_before_qt_receives_arguments(self):
        qt_args, start_in_tray = parse_startup_arguments(["app.exe", "--tray", "-style", "Fusion"])
        self.assertTrue(start_in_tray)
        self.assertEqual(qt_args, ["app.exe", "-style", "Fusion"])

    def test_second_instance_activates_the_primary_instance(self):
        name = f"fileops.test.{uuid.uuid4().hex}"
        primary = SingleInstanceController.acquire(name)
        self.assertIsNotNone(primary)
        spy = QSignalSpy(primary.activation_requested)
        try:
            result = []
            thread = threading.Thread(
                target=lambda: result.append(
                    SingleInstanceController.acquire(name, show_existing=True)
                )
            )
            thread.start()
            QTest.qWait(200)
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(result, [None])
            self.assertEqual(len(spy), 1)
        finally:
            primary.close()


if __name__ == "__main__":
    unittest.main()
