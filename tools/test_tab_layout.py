"""Navigation-only regression checks using real widgets and in-memory settings."""
import copy
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication, QWidget

from src.app_identity import asset_path
from src.core.task_contracts import TaskStep
from src.ui.i18n import tr
from src.ui.main_window import MainWindow, app_stylesheet
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

    def test_indicator_assets_are_resolved_in_application_stylesheet(self):
        stylesheet = app_stylesheet()
        for filename in ("checkmark.svg", "radio-dot.svg"):
            self.assertTrue(asset_path(filename).is_file())
            self.assertIn(asset_path(filename).as_posix(), stylesheet)
        self.assertNotIn("__FILEOPS_", stylesheet)

    def test_compact_sync_window_keeps_scope_and_preview_action_in_view(self):
        self.config.values["sync_groups"] = [
            {"id": "ready", "name": "Ready", "folders": ["C:/Example/A", "C:/Example/B"]},
            {"id": "draft", "name": "Draft", "folders": ["C:/Example/Draft"]},
        ]
        tab = self.window.sync_tab
        self.assertTrue(tab.load_saved_data(persist=False))
        self.window.select_feature_tab(tab)
        self.window.resize(self.window.minimumSize())
        self.window.show()
        for language in ("ko", "en", "pl"):
            with self.subTest(language=language):
                self.config.values["ui_language"] = language
                self.window.refresh_language()
                self.app.processEvents()
                self.assertFalse(tab.analyze_btn.isEnabled())
                self.assertIn("Draft", tab.action_hint_label.text())
                for widget in (tab.sync_scope_label, tab.action_hint_label, tab.analyze_btn):
                    self.assertTrue(widget.isVisibleTo(tab))
                    self.assertTrue(tab.rect().contains(widget.mapTo(tab, QPoint())))
                    self.assertTrue(tab.rect().contains(widget.mapTo(tab, widget.rect().bottomRight())))
        self.assertTrue(tab.incomplete_group_button.isVisibleTo(tab))
        tab.incomplete_group_button.click()
        self.assertEqual(tab.current_group_idx, 1)
        self.assertEqual(tab.folder_list_widget.count(), 1)
        self.assertFalse(tab.analyze_btn.isEnabled())

    def test_compact_task_table_grows_when_log_details_are_closed(self):
        tab = self.window.task_tab
        self.window.select_feature_tab(tab)
        self.window.resize(self.window.minimumSize())
        self.window.show()
        self.app.processEvents()
        self.assertTrue(tab.history_splitter.isHidden())
        closed_height = tab.status_table.height()
        self.assertTrue(tab.history_btn.isVisibleTo(tab))
        tab.log_details_button.click()
        self.app.processEvents()
        self.assertTrue(tab.history_splitter.isVisibleTo(tab))
        self.assertLess(tab.status_table.height(), closed_height)
        actions = [a for a in tab.log_actions_button.menu().actions() if not a.isSeparator()]
        self.assertEqual(len(actions), 5)
        tab.log_details_button.click()
        self.app.processEvents()
        self.assertEqual(tab.status_table.height(), closed_height)

    def test_sync_folders_precede_mode_and_options_do_not_reset(self):
        tab = self.window.sync_tab
        self.config.values["sync_groups"] = [
            {"id": "id", "name": "Example", "folders": ["C:/Example/A", "C:/Example/B"],
             "sync_mode": "one_way", "include_subfolders": True, "exclude_patterns": ["*.tmp"]},
        ]
        self.assertTrue(tab.load_saved_data(persist=False))
        self.window.select_feature_tab(tab)
        self.window.show()
        self.app.processEvents()
        self.assertLess(tab.folder_list_widget.mapTo(tab, QPoint()).y(), tab.mode_group.mapTo(tab, QPoint()).y())
        self.assertEqual(tab.sync_mode_combo.currentData(), "one_way")
        self.assertTrue(tab.advanced_options_panel.isHidden())
        tab.advanced_options_toggle.click()
        self.assertTrue(tab.advanced_options_panel.isVisibleTo(tab))
        self.assertTrue(tab.subfolders_check.isChecked())
        self.assertEqual(tab.exclude_input.text(), "*.tmp")
        tab.advanced_options_toggle.click()
        self.assertTrue(tab.advanced_options_panel.isHidden())
        self.assertTrue(tab.subfolders_check.isChecked())

    def test_compact_conversion_warning_has_room_for_wrapped_text(self):
        tab = self.window.bypass_tab
        self.window.select_feature_tab(tab)
        self.window.resize(self.window.minimumSize())
        self.window.show()
        for language in ("ko", "en", "pl"):
            with self.subTest(language=language):
                self.config.values["ui_language"] = language
                self.window.refresh_language()
                self.app.processEvents()
                hint = tab.source_action_hint
                self.assertGreaterEqual(hint.height(), hint.heightForWidth(hint.width()))
                self.assertFalse(tab.start_btn.isEnabled())
                self.assertEqual(tab.source_folder_button.property("variant"), "primary")

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

    def test_current_screen_help_button_and_menu_follow_selected_child_without_shortcuts(self):
        self.window.select_feature_tab(self.window.pdf_tab)
        with patch.object(self.window, "open_manual") as manual:
            self.window.screen_help_btn.click()
            manual.assert_called_once_with("pdf")
            manual.reset_mock()
            actions = [action for action in self.window.help_menu.actions() if not action.isSeparator()]
            self.assertTrue(all(action.shortcut().isEmpty() for action in actions))
            self.assertEqual([action.text() for action in actions], [
                tr(key, self.window.language)
                for key in ("help_getting_started", "help_current_screen", "check_updates")
            ])
            actions[1].trigger()
            manual.assert_called_once_with("pdf")
            manual.reset_mock()
            actions[0].trigger()
            manual.assert_called_once_with("getting_started")

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
                         (TaskStep.SYNC, TaskStep.COLLECT_SYNC, TaskStep.EML, TaskStep.PDF, TaskStep.OCR))

    def test_unknown_widget_does_not_change_selected_feature(self):
        foreign = QWidget()
        self.addCleanup(foreign.deleteLater)
        before = self.window.tab_widget.currentWidget()
        self.assertFalse(self.window.select_feature_tab(foreign))
        self.assertIs(self.window.tab_widget.currentWidget(), before)


if __name__ == "__main__":
    unittest.main()
