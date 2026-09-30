# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build recipe for the VideoCaptioner desktop bundle.

Produces two executables that share one `_internal` payload:

* ``VideoCaptioner.exe``     -- console build, drives the CLI (and the GUI when
  launched without arguments).
* ``VideoCaptioner-GUI.exe`` -- windowed build, so double-clicking shows the
  desktop app without a stray console window.

Both are optional-free: the icon / version resource are picked up from
``installer/`` when present (see ``installer/build_installer.py --prep``) and
silently skipped otherwise, so a plain checkout still builds.
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

ROOT = Path(SPECPATH)
RUNTIME_DIR = Path(os.environ.get("VIDEOCAPTIONER_DESKTOP_RUNTIME_DIR", ROOT / "build" / "desktop-runtime"))


def _data(src: Path, dest: str):
    return (str(src), dest)


def _optional(path: Path):
    """Return str(path) when the file exists, else None (PyInstaller treats None as unset)."""
    return str(path) if path.exists() else None


ICON_FILE = _optional(ROOT / "installer" / "VideoCaptioner.ico")
VERSION_INFO_CLI = _optional(ROOT / "installer" / "version_info_cli.txt")
VERSION_INFO_GUI = _optional(ROOT / "installer" / "version_info_gui.txt")

datas = [
    _data(ROOT / "resource" / "assets", "resource/assets"),
    _data(ROOT / "resource" / "fonts", "resource/fonts"),
    _data(ROOT / "resource" / "subtitle_style", "resource/subtitle_style"),
    _data(ROOT / "resource" / "translations", "resource/translations"),
    _data(ROOT / "videocaptioner" / "core" / "prompts", "videocaptioner/core/prompts"),
]

runtime_bin = RUNTIME_DIR / "resource" / "bin"
if runtime_bin.exists():
    datas.append(_data(runtime_bin, "resource/bin"))

hiddenimports = [
    "PyQt5",
    "PyQt5.QtCore",
    "PyQt5.QtGui",
    "PyQt5.QtWidgets",
    "PyQt5.QtMultimedia",
    "PyQt5.QtMultimediaWidgets",
    "PyQt5.QtSvg",
    "PyQt5.sip",
    "openai",
    "requests",
    "edge_tts",
    "diskcache",
    "yt_dlp",
    "modelscope",
    "psutil",
    "json_repair",
    "langdetect",
    "pydub",
    "tenacity",
    "GPUtil",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageFont",
    "fontTools",
    "fontTools.ttLib",
]
hiddenimports += collect_submodules("qfluentwidgets")

excludes = [
    "tkinter",
    "matplotlib",
    "scipy",
    "numpy.testing",
    "pytest",
    "pyright",
    "ruff",
    "test",
    "unittest",
]

a = Analysis(
    [str(ROOT / "videocaptioner" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VideoCaptioner",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_FILE,
    version=VERSION_INFO_CLI,
)

collected_exes = [exe]

# Windowed launcher: no console window when the desktop app is opened directly.
if sys.platform == "win32":
    gui_exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="VideoCaptioner-GUI",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=ICON_FILE,
        version=VERSION_INFO_GUI,
    )
    collected_exes.append(gui_exe)

coll = COLLECT(
    *collected_exes,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="VideoCaptioner",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="VideoCaptioner.app",
        bundle_identifier="com.weifeng.videocaptioner",
        info_plist={
            "CFBundleName": "VideoCaptioner",
            "CFBundleDisplayName": "VideoCaptioner",
            "NSHighResolutionCapable": True,
        },
    )
