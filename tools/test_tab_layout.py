"""Navigation-only regression checks using real widgets and in-memory settings."""
import copy
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QWidget

from src.core.task_contracts import TaskStep
from src.ui.i18n import tr
from src.ui.main_window import MainWindow
from src.ui.task_tab import TaskTab
from src.utils.config_manager import ConfigManager


class FakeConfig:
    def __init__(self):
        self.values = copy.deepcopy(ConfigManager.DEFAULT_CONFIG)
        self.values.update(ui_language="ko", auto_check_update="manual", task_schedule_enabled=False,
                           task_folder_watch_enabled=False, sync_groups=[])
        self.app_dir = None

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        return True

    def save_config(self):
        return True


class TabLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.config = FakeConfig()
        with (patch("src.ui.main_window.ConfigManager", return_value=self.config),
              patch.object(MainWindow, "setup_system_tray"),
              patch.object(MainWindow, "trigger_update_check"),
              patch.object(TaskTab, "refresh_readiness")):
            self.window = MainWindow()
        self.window.task_tab.schedule_timer.stop()
        self.window.task_tab.run_health_timer.stop()
        self.window.collect_sync_tab.schedule_timer.stop()

    def tearDown(self):
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()

    def test_top_level_has_requested_five_tabs_in_order(self):
        tabs = self.window.tab_widget
        self.assertEqual(tabs.count(), 5)
        self.assertEqual([tabs.tabText(index) for index in range(5)],
                         ["작업 실행", "폴더 동기화", "자동 수집 동기화", "파일 변환", "SA Team"])
        self.assertEqual([tabs.widget(index) for index in range(5)],
                         [self.window.task_tab, self.window.sync_tab, self.window.collect_sync_tab,
                          self.window.bypass_tab, self.window.sa_team_tabs])

    def test_sa_team_contains_original_feature_widgets_in_order(self):
        tabs = self.window.sa_team_tabs
        self.assertEqual(tabs.count(), 3)
        self.assertEqual([tabs.tabText(index) for index in range(3)],
                         ["EML 변환", "PDF 변환", "이미지 읽기"])
        self.assertEqual([tabs.widget(index) for index in range(3)],
                         [self.window.eml_tab, self.window.pdf_tab, self.window.ocr_tab])
        for tab in (self.window.eml_tab, self.window.pdf_tab, self.window.ocr_tab):
            self.assertIs(tab.window(), self.window)
            self.assertTrue(callable(tab.build_run_config))

    def test_feature_navigation_reveals_both_nested_levels(self):
        for widget, topic in ((self.window.eml_tab, "eml"), (self.window.pdf_tab, "pdf"),
                              (self.window.ocr_tab, "ocr"), (self.window.bypass_tab, "bypass"),
                              (self.window.sync_tab, "sync"), (self.window.collect_sync_tab, "collect_sync"),
                              (self.window.task_tab, "tasks")):
            with self.subTest(topic=topic):
                self.assertTrue(self.window.select_feature_tab(widget))
                self.assertEqual(self.window._current_manual_topic(), topic)
                if topic in ("eml", "pdf", "ocr"):
                    self.assertIs(self.window.tab_widget.currentWidget(), self.window.sa_team_tabs)
                    self.assertIs(self.window.sa_team_tabs.currentWidget(), widget)
                else:
                    self.assertIs(self.window.tab_widget.currentWidget(), widget)

    def test_diagnostic_recovery_reaches_every_feature(self):
        for target in ("eml", "pdf", "ocr", "sync", "bypass", "tasks"):
            with self.subTest(target=target):
                self.window.task_tab._navigate_diagnostic_target(target)
                self.assertEqual(self.window._current_manual_topic(), target)
        self.window.open_settings = Mock()
        self.window.task_tab._navigate_diagnostic_target("settings")
        self.window.open_settings.assert_called_once_with()

    def test_current_screen_help_and_f1_follow_selected_child(self):
        self.window.select_feature_tab(self.window.pdf_tab)
        with patch.object(self.window, "open_manual") as manual:
            self.window.screen_help_btn.click()
            manual.assert_called_once_with("pdf")
            manual.reset_mock()
            f1 = next(action for action in self.window.help_menu.actions() if action.shortcut().toString() == "F1")
            f1.trigger()
            manual.assert_called_once_with("pdf")

    def test_language_switch_translates_both_levels_without_changing_selection(self):
        self.window.select_feature_tab(self.window.ocr_tab)
        for language in ("en", "pl", "ko"):
            with self.subTest(language=language):
                self.config.values["ui_language"] = language
                self.window.refresh_language()
                self.assertEqual([self.window.tab_widget.tabText(i) for i in range(5)],
                                 [tr(key, language) for key in ("tab_tasks", "tab_sync", "tab_collect_sync",
                                                                "tab_bypass", "tab_sa_team")])
                self.assertEqual([self.window.sa_team_tabs.tabText(i) for i in range(3)],
                                 [tr(key, language) for key in ("tab_eml", "tab_pdf", "tab_ocr")])
                self.assertIs(self.window.tab_widget.currentWidget(), self.window.sa_team_tabs)
                self.assertIs(self.window.sa_team_tabs.currentWidget(), self.window.ocr_tab)

    def test_unified_execution_locks_both_navigation_bars(self):
        self.window.select_feature_tab(self.window.eml_tab)
        self.window.set_all_tabs_locked(True)
        self.assertFalse(self.window.tab_widget.tabBar().isEnabled())
        self.assertFalse(self.window.sa_team_tabs.tabBar().isEnabled())
        for tab in (self.window.sync_tab, self.window.collect_sync_tab, self.window.eml_tab,
                    self.window.pdf_tab, self.window.ocr_tab, self.window.bypass_tab):
            self.assertTrue(tab._ui_locked)
        self.window.set_all_tabs_locked(False)
        self.assertTrue(self.window.tab_widget.tabBar().isEnabled())
        self.assertTrue(self.window.sa_team_tabs.tabBar().isEnabled())
        self.assertIs(self.window.sa_team_tabs.currentWidget(), self.window.eml_tab)

    def test_layout_does_not_change_processing_order(self):
        self.assertEqual(self.window.task_tab.STEP_ORDER,
                         (TaskStep.SYNC, TaskStep.EML, TaskStep.PDF, TaskStep.OCR, TaskStep.BYPASS))

    def test_unknown_widget_does_not_change_selected_feature(self):
        foreign = QWidget()
        self.addCleanup(foreign.deleteLater)
        before = self.window.tab_widget.currentWidget()
        self.assertFalse(self.window.select_feature_tab(foreign))
        self.assertIs(self.window.tab_widget.currentWidget(), before)


if __name__ == "__main__":
    unittest.main()
