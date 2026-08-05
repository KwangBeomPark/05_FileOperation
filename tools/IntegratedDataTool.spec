# -*- mode: python ; coding: utf-8 -*-

import os

from PyInstaller.utils.hooks import collect_all

block_cipher = None
PROJECT_ROOT = os.path.dirname(SPECPATH)
VERSION_FILE = os.environ.get("FILEOPS_VERSION_FILE")
if not VERSION_FILE or not os.path.exists(VERSION_FILE):
    raise RuntimeError("FILEOPS_VERSION_FILE must point to the generated PyInstaller version resource.")
playwright_datas, playwright_binaries, playwright_hiddenimports = collect_all("playwright")
qtawesome_datas, qtawesome_binaries, qtawesome_hiddenimports = collect_all("qtawesome")

a = Analysis(
    [os.path.join(PROJECT_ROOT, 'src', 'main.py')],
    pathex=[PROJECT_ROOT],
    binaries=playwright_binaries + qtawesome_binaries,
    datas=[
        (os.path.join(PROJECT_ROOT, 'src', 'assets'), 'src/assets'),
    ] + playwright_datas + qtawesome_datas,
    hiddenimports=[
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'pythoncom',
        'pywintypes',
        'win32com.client',
    ] + playwright_hiddenimports + qtawesome_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='IntegratedDataTool',
    icon=os.path.join(PROJECT_ROOT, 'src', 'assets', 'icon.ico'),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    version=VERSION_FILE,
    codesign_identity=None,
    entitlements_file=None,
)
