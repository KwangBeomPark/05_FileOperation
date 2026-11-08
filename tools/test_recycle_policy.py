"""Pure tests: no real files are sent to the Recycle Bin."""

import unittest
from unittest.mock import patch

from src.core.recycle_policy import (
    DeleteCallback,
    RecycleEvidence,
    RecycleOutcome,
    classify_recycle_evidence,
    inspect_source_presence,
)


class RecyclePolicyTests(unittest.TestCase):
    def test_inaccessible_path_is_unknown_not_missing(self):
        self.assertIsNone(inspect_source_presence(""))
        with patch("src.core.recycle_policy.os.lstat", side_effect=PermissionError("denied")):
            self.assertIsNone(inspect_source_presence("a.txt"))

    def test_file_not_found_is_distinct_from_access_error(self):
        with patch("src.core.recycle_policy.os.lstat", side_effect=FileNotFoundError("missing")):
            self.assertIs(inspect_source_presence("a.txt"), False)

    def test_shell_positive_success_status_with_recycled_item(self):
        evidence = RecycleEvidence("a.txt", (DeleteCallback("a.txt", 0x00270008, True),), False, False, False)
        self.assertEqual(classify_recycle_evidence(evidence), RecycleOutcome.SHELL_CONFIRMED_RECYCLE)

    def test_unobserved_positive_status_is_not_accepted(self):
        evidence = RecycleEvidence("a.txt", (DeleteCallback("a.txt", 1, True),), False, False, False)
        self.assertEqual(classify_recycle_evidence(evidence), RecycleOutcome.UNCERTAIN)

    def test_failure_hresult_is_never_success_even_if_unsigned(self):
        for hresult in (-2147467259, 0x80004005):
            with self.subTest(hresult=hresult):
                evidence = RecycleEvidence("a.txt", (DeleteCallback("a.txt", hresult, True),), False, False, False)
                self.assertEqual(classify_recycle_evidence(evidence), RecycleOutcome.UNCERTAIN)

    def test_missing_or_wrong_item_never_claims_success(self):
        cases = ((), (DeleteCallback("other/a.txt", 0, True),),
                 (DeleteCallback("a.txt", 0, False),),
                 (DeleteCallback("a.txt", 0, True), DeleteCallback("a.txt", 0, True)))
        for callbacks in cases:
            with self.subTest(callbacks=callbacks):
                evidence = RecycleEvidence("a.txt", callbacks, False, False, False)
                self.assertEqual(classify_recycle_evidence(evidence), RecycleOutcome.UNCERTAIN)

    def test_operation_failure_abort_or_unknown_source_is_not_success(self):
        callback = (DeleteCallback("a.txt", 0, True),)
        for failed, aborted, exists in ((True, False, False), (False, True, False), (False, False, None)):
            with self.subTest(failed=failed, aborted=aborted, exists=exists):
                evidence = RecycleEvidence("a.txt", callback, failed, aborted, exists)
                self.assertEqual(classify_recycle_evidence(evidence), RecycleOutcome.UNCERTAIN)

    def test_existing_source_is_not_reported_as_recycled(self):
        evidence = RecycleEvidence("a.txt", (), True, False, True)
        self.assertEqual(classify_recycle_evidence(evidence), RecycleOutcome.SOURCE_PATH_PRESENT)
