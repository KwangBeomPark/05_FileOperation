"""Opt-in Windows Shell experiment using only newly created synthetic files.

This is a manual diagnostic, not the FileOps recycling implementation. It never
accepts a path to an existing file. A confirmed move still requires the user to
inspect the Recycle Bin; unsupported and crash-recovery cases are not proven.
"""

import argparse
import sys
import tempfile
import time
import uuid
from pathlib import Path
from unittest.mock import patch


def _hresult_succeeded(value):
    """Check the HRESULT severity bit for signed and unsigned representations."""
    return (int(value) & 0x80000000) == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("success", "reject"), required=True)
    parser.add_argument("--allow-real-recycle", action="store_true")
    args = parser.parse_args()
    if not args.allow_real_recycle:
        parser.error("Explicit --allow-real-recycle is required for this synthetic test.")
    if sys.platform != "win32":
        parser.error("This Windows Shell experiment requires Windows.")

    import pythoncom
    from send2trash.win import modern
    from send2trash.win.IFileOperationProgressSink import FileOperationProgressSink
    from win32com.server.exception import COMException
    from win32com.shell import shell

    class ProbeSink(FileOperationProgressSink):
        def __init__(self):
            super().__init__()
            self.pre_called = False
            self.callbacks = []

        def PreDeleteItem(self, flags, item):
            self.pre_called = True
            if args.mode == "reject":
                raise COMException(desc="Synthetic test: block delete", scode=-2147467259)
            return super().PreDeleteItem(flags, item)

        def PostDeleteItem(self, flags, item, hr_delete, newly_created):
            self.callbacks.append((int(hr_delete), newly_created is not None))
            return super().PostDeleteItem(flags, item, hr_delete, newly_created)

    # Keep this empty directory so the user can restore the test item into it.
    root = Path(tempfile.mkdtemp(prefix="FileOps-ShellProbe-"))
    path = root / f"FileOps_ShellProbe_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.txt"
    data = b"Synthetic FileOps Shell test; contains no user data.\n"
    path.write_bytes(data)
    sink = ProbeSink()
    wrapped = pythoncom.WrapObject(sink, shell.IID_IFileOperationProgressSink)
    failure = None
    try:
        with patch.object(modern, "create_sink", return_value=wrapped):
            modern.send2trash(str(path))
    except Exception as exc:  # noqa: BLE001 - report the diagnostic failure type
        failure = exc

    print(f"TEST_PATH={path}")
    print(f"PRE_CALLED={sink.pre_called}")
    print(f"CALLBACKS={sink.callbacks}")
    print(f"SOURCE_UNCHANGED={path.exists() and path.read_bytes() == data}")
    print(f"ERROR_TYPE={type(failure).__name__ if failure else ''}")
    if args.mode == "reject":
        return 0 if sink.pre_called and failure is not None and path.exists() and path.read_bytes() == data else 1
    return 0 if failure is None and not path.exists() and any(
        _hresult_succeeded(hr) and recycled for hr, recycled in sink.callbacks
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
