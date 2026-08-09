import os
import unittest
from unittest.mock import Mock, patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

from src.ui.main_window import MainWindow
from src.ui.i18n import tr


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

    def test_manual_entry_points_follow_the_current_tab_and_language(self):
        self.assertEqual(
            self.window.screen_help_btn.text(),
            tr("help_current_screen", self.window.language),
        )
        self.window.tab_widget.setCurrentWidget(self.window.sync_tab)
        self.assertEqual(self.window._current_manual_topic(), "sync")
        help_actions = [action.text() for action in self.window.help_menu.actions()]
        self.assertIn(tr("help_getting_started", self.window.language), help_actions)
        self.assertIn(tr("help_user_manual", self.window.language), help_actions)


if __name__ == "__main__":
    unittest.main()
