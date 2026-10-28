"""Actual QThread recovery UI, consent, cancellation and modal execution gate."""

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication, QDialog

from src.core.collect_recovery import RecoveryPreview
from src.core.collect_sync import CollectState
from src.ui.collect_recovery_dialog import CollectRecoveryDialog
from src.ui.i18n import tr
from tools.test_collect_sync_ui import wait_until


class RecoveryDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source, self.target = (
            self.root / "source.txt",
            self.root / "target" / "source.txt",
        )
        self.target.parent.mkdir()
        self.source.write_text("same", encoding="utf-8")
        self.target.write_text("same", encoding="utf-8")
        self.state_path = self.root / "state.json"
        state = CollectState(self.state_path)
        state.pending = {
            "source": str(self.source),
            "target": str(self.target.parent),
            "name": self.target.name,
        }
        state.save()
        self.dialog = None

    def tearDown(self):
        if self.dialog:
            self.dialog.reject()
            wait_until(lambda: self.dialog.worker is None)
            self.dialog.deleteLater()
            self.app.processEvents()
        self.temporary.cleanup()

    def open_dialog(self, language="en"):
        self.dialog = CollectRecoveryDialog(self.state_path, language)
        self.dialog.show()
        wait_until(lambda: self.dialog.preview is not None)
        return self.dialog

    def test_matching_file_needs_consent_and_cancel_is_default(self):
        dialog = self.open_dialog()
        self.assertFalse(dialog.adopt_button.isEnabled())
        self.assertFalse(dialog.preserve_button.isEnabled())
        self.assertTrue(dialog.cancel_button.isDefault())
        dialog._apply("adopt")
        self.assertIsNone(dialog.worker)
        self.assertTrue(CollectState.load(self.state_path, allow_pending=True).pending)
        dialog.consent.setChecked(True)
        self.assertFalse(dialog.adopt_button.isEnabled())
        dialog.ownership.setChecked(True)
        self.assertTrue(dialog.adopt_button.isEnabled())

    def test_unverified_release_needs_extra_explicit_consent(self):
        self.target.parent.rename(self.root / "renamed")
        dialog = self.open_dialog("ko")
        self.assertEqual(dialog.preview.status, "unverified")
        dialog.consent.setChecked(True)
        self.assertFalse(dialog.preserve_button.isEnabled())
        dialog._apply("preserve")
        self.assertIsNone(dialog.worker)
        self.assertTrue(CollectState.load(self.state_path, allow_pending=True).pending)
        dialog.unverified_consent.setChecked(True)
        self.assertTrue(dialog.preserve_button.isEnabled())
        self.assertFalse(dialog.adopt_button.isEnabled())
        dialog._apply("preserve")
        wait_until(lambda: dialog.worker is None)
        self.assertTrue(dialog.backup_path.exists())
        self.assertFalse(CollectState.load(self.state_path).pending)

    def test_retry_after_temporary_target_lock_returns_to_verified_preview(self):
        real_open = Path.open

        def open_path(path, *args, **kwargs):
            if path == self.target:
                raise PermissionError("temporary target lock")
            return real_open(path, *args, **kwargs)

        with patch.object(Path, "open", open_path):
            dialog = self.open_dialog()
        self.assertEqual(dialog.preview.status, "unverified")
        dialog.consent.setChecked(True)
        dialog.unverified_consent.setChecked(True)
        dialog.retry_button.click()
        wait_until(lambda: dialog.preview is not None and dialog.worker is None)
        self.assertEqual(dialog.preview.status, "matching")
        self.assertFalse(dialog.consent.isChecked())
        self.assertFalse(dialog.unverified_consent.isChecked())
        self.assertFalse(dialog.adopt_button.isEnabled())
        self.assertTrue(CollectState.load(self.state_path, allow_pending=True).pending)

    def test_old_unc_name_pending_offers_explicit_record_only_release(self):
        state = CollectState.load(self.state_path, allow_pending=True)
        state.pending["name"] = r"report [\\nas\share].txt"
        state.save()
        dialog = self.open_dialog()
        self.assertEqual(dialog.preview.status, "unverified")
        dialog.consent.setChecked(True)
        dialog.unverified_consent.setChecked(True)
        dialog.preserve_button.click()
        wait_until(lambda: dialog.worker is None)
        self.assertFalse(CollectState.load(self.state_path).pending)
        self.assertEqual(self.target.read_text(encoding="utf-8"), "same")

    def test_corrupt_mapping_does_not_offer_metadata_release(self):
        state = CollectState.load(self.state_path, allow_pending=True)
        state.targets["target"] = {"source": "../escape"}
        state.save()
        self.dialog = CollectRecoveryDialog(self.state_path, "en")
        self.dialog.show()
        wait_until(
            lambda: (
                self.dialog.worker is None and "could not" in self.dialog.status.text()
            )
        )
        self.assertIsNone(self.dialog.preview)
        self.dialog.consent.setChecked(True)
        self.dialog.unverified_consent.setChecked(True)
        self.assertFalse(self.dialog.preserve_button.isEnabled())

    def test_preserve_recovery_runs_and_returns_backup_without_changing_files(self):
        dialog = self.open_dialog()
        dialog.consent.setChecked(True)
        dialog._apply("preserve")
        wait_until(lambda: dialog.worker is None)
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertTrue(dialog.backup_path.exists())
        self.assertFalse(CollectState.load(self.state_path).pending)
        self.assertEqual(self.target.read_text(encoding="utf-8"), "same")

    def test_different_file_cannot_be_adopted_even_programmatically(self):
        self.target.write_text("user file", encoding="utf-8")
        dialog = self.open_dialog()
        dialog.consent.setChecked(True)
        self.assertFalse(dialog.adopt_button.isEnabled())
        dialog._apply("adopt")
        self.assertIsNone(dialog.worker)
        self.assertTrue(CollectState.load(self.state_path, allow_pending=True).pending)

    def test_stale_preview_blocks_apply_and_preserves_pending(self):
        dialog = self.open_dialog()
        self.target.write_text("changed", encoding="utf-8")
        dialog.consent.setChecked(True)
        dialog.ownership.setChecked(True)
        dialog._apply("adopt")
        wait_until(lambda: dialog.worker is None)
        self.assertEqual(dialog.status.text(), tr("collect_recovery_stale", "en"))
        self.assertTrue(CollectState.load(self.state_path, allow_pending=True).pending)

    def test_programmatic_adopt_also_requires_separate_ownership_confirmation(self):
        dialog = self.open_dialog()
        dialog.consent.setChecked(True)
        dialog._apply("adopt")
        self.assertIsNone(dialog.worker)
        self.assertTrue(CollectState.load(self.state_path, allow_pending=True).pending)

    def test_slow_inspection_is_not_on_gui_and_close_waits_for_worker(self):
        entered, release = threading.Event(), threading.Event()
        threads = []

        def inspect(*_args):
            threads.append(threading.get_ident())
            entered.set()
            release.wait(3)
            return RecoveryPreview("none")

        with patch(
            "src.ui.collect_recovery_dialog.inspect_pending_copy", side_effect=inspect
        ):
            try:
                self.dialog = CollectRecoveryDialog(self.state_path, "en")
                self.dialog.show()
                wait_until(entered.is_set)
                self.dialog.reject()
                self.assertTrue(self.dialog.isVisible())
                self.assertIsNotNone(self.dialog.worker)
                release.set()
                wait_until(lambda: self.dialog.worker is None)
            finally:
                release.set()
        self.assertNotEqual(threads[0], threading.get_ident())
        self.assertFalse(self.dialog.isVisible())

    def test_language_catalogs_provide_recovery_dialog(self):
        for language in ("ko", "en", "pl"):
            dialog = CollectRecoveryDialog(self.state_path, language)
            dialog.reject()
            self.assertEqual(
                dialog.windowTitle(), tr("collect_recovery_title", language)
            )
            dialog.deleteLater()
        self.app.processEvents()
