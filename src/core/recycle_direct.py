"""Windows recycle-only call for manual version cleanup, not date sync.

The device gate relies on conservative OS-reported device evidence, which
cannot rule out incorrect drivers. A successful Shell result is not a
guarantee of future recovery or of protection from Recycle Bin policy.
"""

import os
import struct

from src.core.recycle_policy import inspect_source_presence


def _require_internal_physical_volume(path):
    """Require corroborating OS evidence; driver reports can still be wrong."""
    try:
        evidence = _read_device_evidence(path)
    except Exception as exc:
        raise OSError("Unable to establish internal physical storage; recycling blocked") from exc
    if (evidence["drive_type"] != 3 or evidence["extent_count"] != 1
            or evidence["bus"] not in (3, 11, 17)  # ATA, SATA, NVMe only
            or evidence["removable"] != 0
            or evidence["media_removable"] != 0 or evidence["media_hotplug"] != 0
            or evidence["device_hotplug"] != 0):
        raise OSError("Volume is not confirmed non-removable internal physical storage; recycling blocked")


def _read_device_evidence(path):
    """Read volume/disk metadata without administrator privileges or writes.

    Only a drive-letter root is accepted; mount points, multiple extents,
    unsupported drivers and malformed/short device replies fail closed.
    """
    import win32con
    import win32file

    root = win32file.GetVolumePathName(path)
    drive, tail = os.path.splitdrive(root)
    if len(drive) != 2 or drive[1] != ":" or tail != "\\":
        raise OSError("Unsupported volume path; recycling blocked")
    drive_type = win32file.GetDriveType(root)
    if drive_type != win32file.DRIVE_FIXED:
        raise OSError("Non-fixed volume; recycling blocked")

    def ioctl(device, code, request, size):
        handle = win32file.CreateFile(device, 0, win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
                                      None, win32con.OPEN_EXISTING, 0, None)
        try:
            return win32file.DeviceIoControl(handle, code, request, size)
        finally:
            handle.Close()

    try:
        extents = ioctl("\\\\.\\" + drive, 0x00560000, None, 32)
        if len(extents) < 32 or struct.unpack_from("<I", extents)[0] != 1:
            raise OSError("Volume has unsupported disk extents")
        disk = struct.unpack_from("<I", extents, 8)[0]
        device = "\\\\.\\PhysicalDrive" + str(disk)
        descriptor = ioctl(device, 0x002D1400, struct.pack("<III", 0, 0, 0), 1024)
        if len(descriptor) < 36:
            raise OSError("Short storage descriptor")
        version, size = struct.unpack_from("<II", descriptor)
        if version < 36 or size < 36 or size > len(descriptor) or descriptor[8] != 0:
            raise OSError("Unsupported storage descriptor")
        hotplug = ioctl(device, 0x002D0C14, None, 8)
        if len(hotplug) < 8 or struct.unpack_from("<I", hotplug)[0] < 8:
            raise OSError("Short hotplug descriptor")
        return {"drive_type": drive_type, "extent_count": 1, "bus": struct.unpack_from("<I", descriptor, 28)[0],
                "removable": descriptor[10], "media_removable": hotplug[4],
                "media_hotplug": hotplug[5], "device_hotplug": hotplug[6]}
    except Exception as exc:
        raise OSError("Unable to establish internal physical storage; recycling blocked") from exc


def _shell_recycle(path):
    import pythoncom
    from win32com.shell import shell

    pythoncom.CoInitialize()
    try:
        item = shell.SHCreateItemFromParsingName(path, None, shell.IID_IShellItem)
        parent = item.GetParent()
        source = parent.BindToHandler(None, shell.BHID_Transfer, shell.IID_ITransferSource)
        destination = shell.SHCreateItemInKnownFolder(
            shell.FOLDERID_RecycleBinFolder, 0, None, shell.IID_IShellItem
        )
        # TSF_NORMAL: no automatic confirmation or permanent-delete fallback.
        return source.RecycleItem(item, destination, 0)
    finally:
        pythoncom.CoUninitialize()


def recycle_file(path):
    """Attempt recycling only after the internal-device gate permits it.

    Caller must validate approval, path, file identity and cancellation.  An
    error after invoking the Shell does not imply that the source survived.
    """
    path = os.path.abspath(os.fspath(path))
    if os.name != "nt":
        raise OSError("Windows recycling is unavailable on this platform")
    _require_internal_physical_volume(path)
    try:
        result, recycled_item = _shell_recycle(path)
    except Exception as exc:
        presence = inspect_source_presence(path)
        raise OSError(f"Recycle operation failed; source presence={presence}; outcome may be uncertain") from exc
    presence = inspect_source_presence(path)
    if (int(result) & 0xFFFFFFFF) not in (0, 0x00270008) or recycled_item is None or presence is not False:
        raise OSError(f"Recycle operation not confirmed; source presence={presence}; outcome may be uncertain")
