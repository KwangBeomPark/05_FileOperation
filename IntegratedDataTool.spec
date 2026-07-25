# -*- mode: python ; coding: utf-8 -*-

import os

from PyInstaller.utils.hooks import collect_all

block_cipher = None
PROJECT_ROOT = os.path.abspath(".")
VERSION_FILE = os.environ.get("FILEOPS_VERSION_FILE")
if not VERSION_FILE or not os.path.exists(VERSION_FILE):
    raise RuntimeError("FILEOPS_VERSION_FILE must point to the generated PyInstaller version resource.")
playwright_datas, playwright_binaries, playwright_hiddenimports = collect_all("playwright")

a = Analysis(
    ['src/main.py'],
    pathex=[PROJECT_ROOT],
    binaries=playwright_binaries,
    datas=[
        # 필요한 데이터 파일이나 환경설정 템플릿 등이 있다면 여기에 등록
    ] + playwright_datas,
    hiddenimports=[
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'pythoncom',
        'pywintypes',
        'win32com.client',
    ] + playwright_hiddenimports,
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
