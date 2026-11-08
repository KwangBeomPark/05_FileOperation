"""Non-destructive checks for the opt-in Windows diagnostic."""

import sys
import unittest
from unittest.mock import patch

from tools.manual_recycle_probe import _hresult_succeeded, main


class ManualRecycleProbeTests(unittest.TestCase):
    def test_hresult_severity_bit_handles_signed_and_unsigned_values(self):
        self.assertTrue(_hresult_succeeded(0))
        self.assertTrue(_hresult_succeeded(0x00270008))
        self.assertFalse(_hresult_succeeded(-2147467259))
        self.assertFalse(_hresult_succeeded(0x80004005))

    def test_explicit_opt_in_is_required_before_creating_any_file(self):
        with (patch.object(sys, "argv", ["probe", "--mode", "success"]),
              patch("tools.manual_recycle_probe.tempfile.mkdtemp") as make_dir,
              self.assertRaises(SystemExit) as exc):
            main()
        self.assertEqual(exc.exception.code, 2)
        make_dir.assert_not_called()
