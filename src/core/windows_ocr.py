from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

WINDOWS_OCR_MAX_DIMENSION = 2600


POWERSHELL_OCR_SCRIPT = r"""
param(
    [string]$Path,
    [switch]$CheckOnly
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType = WindowsRuntime]

if ($CheckOnly) {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    if ($null -eq $engine) {
        throw "No Windows OCR engine is available for the current user profile languages."
    }
    "Windows OCR available"
    exit 0
}

$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.FileAccessMode, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrResult, Windows.Media.Ocr, ContentType = WindowsRuntime]

$asTaskMethods = [System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object { $_.Name -eq "AsTask" -and $_.IsGenericMethodDefinition -and $_.GetParameters().Count -eq 1 }

function Await-Operation($operation, [type]$resultType) {
    $method = $script:asTaskMethods |
        Where-Object { $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } |
        Select-Object -First 1
    if ($null -eq $method) {
        throw "Windows Runtime async bridge is unavailable."
    }
    $task = $method.MakeGenericMethod($resultType).Invoke($null, @($operation))
    $task.Wait()
    return $task.Result
}

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) {
    throw "No Windows OCR engine is available for the current user profile languages."
}

$file = Await-Operation ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)) ([Windows.Storage.StorageFile])
$stream = Await-Operation ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
try {
    $decoder = Await-Operation ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await-Operation ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $result = Await-Operation ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    $result.Text
}
finally {
    if ($stream -ne $null) {
        $stream.Dispose()
    }
}
"""


def _powershell_executable() -> str:
    return "powershell.exe" if sys.platform == "win32" else ""


def _run_powershell(script_path: str, args: list[str], timeout_seconds: int) -> subprocess.CompletedProcess:
    executable = _powershell_executable()
    if not executable:
        raise RuntimeError("Windows OCR은 Windows에서만 사용할 수 있습니다.")

    return subprocess.run(
        [executable, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )


def _write_script() -> str:
    handle = tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8-sig")
    try:
        handle.write(POWERSHELL_OCR_SCRIPT)
        return handle.name
    finally:
        handle.close()


def _prepare_image(image_path: str) -> tuple[str, bool]:
    image = Image.open(image_path)
    try:
        original_format = image.format
        image = image.convert("RGB")
        width, height = image.size
        max_dimension = max(width, height)
        should_copy = original_format not in {"PNG", "JPEG", "BMP"} or max_dimension > WINDOWS_OCR_MAX_DIMENSION

        if max_dimension > WINDOWS_OCR_MAX_DIMENSION:
            scale = WINDOWS_OCR_MAX_DIMENSION / max_dimension
            new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
            image = image.resize(new_size)

        if should_copy:
            fd, temp_path = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            image.save(temp_path, format="PNG")
            return temp_path, True
        return image_path, False
    finally:
        image.close()


def windows_ocr_available(timeout_seconds: int = 8) -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "Windows OCR은 Windows에서만 사용할 수 있습니다."

    script_path = _write_script()
    try:
        completed = _run_powershell(script_path, ["-CheckOnly"], timeout_seconds)
        if completed.returncode == 0:
            return True, "Windows 내장 OCR 사용 가능"
        detail = (completed.stderr or completed.stdout or "Windows OCR check failed").strip()
        return False, detail
    except Exception as exc:
        return False, str(exc)
    finally:
        try:
            Path(script_path).unlink(missing_ok=True)
        except Exception:
            pass


def extract_text_with_windows_ocr(image_path: str, timeout_seconds: int = 30) -> str:
    if not os.path.exists(image_path):
        raise FileNotFoundError(image_path)

    prepared_path, is_temp_image = _prepare_image(image_path)
    script_path = _write_script()
    try:
        completed = _run_powershell(script_path, ["-Path", prepared_path], timeout_seconds)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "Windows OCR failed").strip()
            raise RuntimeError(detail)
        return completed.stdout.strip()
    finally:
        try:
            Path(script_path).unlink(missing_ok=True)
        except Exception:
            pass
        if is_temp_image:
            try:
                Path(prepared_path).unlink(missing_ok=True)
            except Exception:
                pass
