import struct
import unittest
from unittest.mock import Mock, patch

from src.core import recycle_direct


class DirectRecycleTests(unittest.TestCase):
    def test_device_responses_and_paths(self):
        import win32file

        extent = bytearray(32)
        struct.pack_into("<I", extent, 0, 1)
        struct.pack_into("<I", extent, 8, 7)
        descriptor = bytearray(36)
        struct.pack_into("<II", descriptor, 0, 36, 36)
        struct.pack_into("<I", descriptor, 28, 17)
        hotplug = bytearray(8)
        struct.pack_into("<I", hotplug, 0, 8)

        def run(root="C:\\", drive_type=3, extent_reply=None, descriptor_reply=None,
                hotplug_reply=None, open_error=None):
            replies = [bytes(extent if extent_reply is None else extent_reply),
                       bytes(descriptor if descriptor_reply is None else descriptor_reply),
                       bytes(hotplug if hotplug_reply is None else hotplug_reply)]
            handles = []

            def open_device(*args):
                if open_error:
                    raise open_error
                handle = Mock()
                handles.append(handle)
                return handle

            with patch.object(win32file, "GetVolumePathName", return_value=root), \
                    patch.object(win32file, "GetDriveType", return_value=drive_type), \
                    patch.object(win32file, "CreateFile", side_effect=open_device) as create, \
                    patch.object(win32file, "DeviceIoControl", side_effect=replies) as ioctl:
                try:
                    recycle_direct._require_internal_physical_volume("C:\\test\\file.txt")
                finally:
                    for handle in handles:
                        handle.Close.assert_called_once()
            return create, ioctl

        create, ioctl = run()
        self.assertEqual(create.call_args_list[0].args[0], "\\\\.\\C:")
        self.assertEqual(create.call_args_list[1].args[0], "\\\\.\\PhysicalDrive7")
        self.assertEqual([call.args[1] for call in ioctl.call_args_list],
                         [0x00560000, 0x002D1400, 0x002D0C14])

        multiple = bytearray(extent)
        struct.pack_into("<I", multiple, 0, 2)
        usb = bytearray(descriptor)
        struct.pack_into("<I", usb, 28, 7)
        unknown = bytearray(descriptor)
        struct.pack_into("<I", unknown, 28, 0)
        removable = bytearray(descriptor)
        removable[10] = 1
        hot = bytearray(hotplug)
        hot[6] = 1
        cases = [{"root": "\\\\server\\share\\"}, {"root": "C:\\mount\\"},
                 {"drive_type": 4}, {"extent_reply": multiple}, {"extent_reply": b"short"},
                 {"descriptor_reply": b"short"}, {"hotplug_reply": b"short"},
                 {"descriptor_reply": usb}, {"descriptor_reply": unknown},
                 {"descriptor_reply": removable}, {"hotplug_reply": hot},
                 {"open_error": PermissionError("denied")}]
        for case in cases:
            with self.subTest(case=case), self.assertRaisesRegex(OSError, "blocked"):
                run(**case)

    def test_real_device_gate_blocks_before_shell(self):
        with patch.object(recycle_direct.os, "name", "nt"), patch.object(recycle_direct, "_read_device_evidence", side_effect=OSError("blocked")), patch.object(recycle_direct, "_shell_recycle") as shell:
            with self.assertRaisesRegex(OSError, "blocked"):
                recycle_direct.recycle_file("example.txt")
            shell.assert_not_called()

    def test_device_gate_requires_all_corroborating_evidence(self):
        valid = {"drive_type": 3, "extent_count": 1, "bus": 17, "removable": 0,
                     "media_removable": 0, "media_hotplug": 0, "device_hotplug": 0}
        with patch.object(recycle_direct, "_read_device_evidence", return_value=valid):
            recycle_direct._require_internal_physical_volume("example.txt")
        for field, value in (("drive_type", 4), ("extent_count", 2), ("bus", 7),
                             ("bus", 14), ("bus", 15), ("bus", 0), ("removable", 1),
                             ("media_removable", 1), ("media_hotplug", 1), ("device_hotplug", 1)):
            evidence = dict(valid, **{field: value})
            with self.subTest(field=field, value=value), patch.object(recycle_direct, "_read_device_evidence", return_value=evidence), self.assertRaisesRegex(OSError, "blocked"):
                recycle_direct._require_internal_physical_volume("example.txt")

    def test_confirmed_result_requires_item_and_missing_source(self):
        with patch.object(recycle_direct.os, "name", "nt"), \
                patch.object(recycle_direct, "_require_internal_physical_volume"), \
                patch.object(recycle_direct, "_shell_recycle", return_value=(0x270008, object())), \
                patch.object(recycle_direct, "inspect_source_presence", return_value=False):
            recycle_direct.recycle_file("example.txt")

    def test_unconfirmed_outcomes_fail_closed(self):
        for result, item, presence in ((0, None, False), (0, object(), True),
                                       (0x27000B, object(), False), (0, object(), None)):
            with self.subTest(result=result, presence=presence), \
                    patch.object(recycle_direct.os, "name", "nt"), \
                    patch.object(recycle_direct, "_require_internal_physical_volume"), \
                    patch.object(recycle_direct, "_shell_recycle", return_value=(result, item)), \
                    patch.object(recycle_direct, "inspect_source_presence", return_value=presence), \
                    self.assertRaisesRegex(OSError, "not confirmed"):
                recycle_direct.recycle_file("example.txt")

    def test_shell_error_does_not_claim_source_preserved(self):
        with patch.object(recycle_direct.os, "name", "nt"), \
                patch.object(recycle_direct, "_require_internal_physical_volume"), \
                patch.object(recycle_direct, "_shell_recycle", side_effect=RuntimeError("failure")), \
                patch.object(recycle_direct, "inspect_source_presence", return_value=None), \
                self.assertRaisesRegex(OSError, "outcome may be uncertain"):
            recycle_direct.recycle_file("example.txt")

    def test_shell_uses_parent_and_normal_flags(self):
        import pythoncom
        from win32com.shell import shell

        item, parent, source, destination = Mock(), Mock(), Mock(), Mock()
        item.GetParent.return_value = parent
        parent.BindToHandler.return_value = source
        source.RecycleItem.return_value = (0, object())
        with patch.object(pythoncom, "CoInitialize"), patch.object(pythoncom, "CoUninitialize") as uninit, \
                patch.object(shell, "SHCreateItemFromParsingName", return_value=item), \
                patch.object(shell, "SHCreateItemInKnownFolder", return_value=destination):
            recycle_direct._shell_recycle("example.txt")
        parent.BindToHandler.assert_called_once_with(None, shell.BHID_Transfer, shell.IID_ITransferSource)
        source.RecycleItem.assert_called_once_with(item, destination, 0)
        uninit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
