import os
import unittest
from unittest.mock import Mock, patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

from src.ui.main_window import MainWindow


class SystemTrayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        with (
            patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True),
            patch.object(MainWindow, "trigger_update_check"),
        ):
            self.window = MainWindow()
        self.window.save_window_state = Mock()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        if self.window.tray_icon:
            self.window.tray_icon.hide()
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()

    def test_window_close_hides_to_tray_and_keeps_process_available(self):
        event = QCloseEvent()

        self.window.closeEvent(event)

        self.assertFalse(event.isAccepted())
        self.assertTrue(self.window.isHidden())
        self.assertTrue(self.window.tray_icon.isVisible())
        self.window.save_window_state.assert_called_once_with()

        self.window.show_from_tray()
        self.app.processEvents()
        self.assertTrue(self.window.isVisible())

    def test_explicit_exit_accepts_close_and_hides_tray_icon(self):
        self.window._is_exiting = True
        event = QCloseEvent()

        self.window.closeEvent(event)

        self.assertTrue(event.isAccepted())
        self.assertFalse(self.window.tray_icon.isVisible())


if __name__ == "__main__":
    unittest.main()
