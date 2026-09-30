#!/usr/bin/env python3
"""Build a Windows installer (.exe) for VideoCaptioner from the PyInstaller bundle.

Pipeline:
    1. scripts/build_desktop.py --clean      -> dist/VideoCaptioner (portable bundle)
    2. installer/build_installer.py --prep   -> generate icon + version resource
    3. scripts/build_desktop.py --clean      -> rebuild with icon / GUI launcher
    4. installer/build_installer.py          -> artifacts/VideoCaptioner-<ver>-windows-x64-setup.exe

Requires a working `makensis` (NSIS 3.x). Resolution order:
    --makensis <path>  ->  $MAKENSIS  ->  tools/nsis  ->  PATH  ->  common install dirs.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALLER_DIR = ROOT / "installer"
BUNDLE_DIR = ROOT / "dist" / "VideoCaptioner"
ARTIFACT_DIR = ROOT / "artifacts"

NSI_FILE = INSTALLER_DIR / "installer.nsi"
ICON_FILE = INSTALLER_DIR / "VideoCaptioner.ico"
VERSION_INFO_CLI = INSTALLER_DIR / "version_info_cli.txt"
VERSION_INFO_GUI = INSTALLER_DIR / "version_info_gui.txt"
LICENSE_FILE = ROOT / "LICENSE"
LOGO_SRC = ROOT / "resource" / "assets" / "logo.png"

APP_NAME = "VideoCaptioner"
APP_PUBLISHER = "WEIFENG2333"
APP_URL = "https://github.com/WEIFENG2333/VideoCaptioner"

MAKENSIS_CANDIDATES = [
    Path("E:/workbuddy/tools/nsis/nsis-3.10/Bin/makensis.exe"),
    Path("C:/Program Files (x86)/NSIS/makensis.exe"),
    Path("C:/Program Files/NSIS/makensis.exe"),
]

VERSION_INFO_TEMPLATE = """\
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={quad},
    prodvers={quad},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('080404B0', [
        StringStruct('CompanyName', '{publisher}'),
        StringStruct('FileDescription', '{description}'),
        StringStruct('FileVersion', '{quad_text}'),
        StringStruct('InternalName', '{internal}'),
        StringStruct('LegalCopyright', 'GNU GPL v3.0'),
        StringStruct('OriginalFilename', '{original}'),
        StringStruct('ProductName', '{app}'),
        StringStruct('ProductVersion', '{version}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""


# ------------------------------------------------------------------ helpers ---


def log(message: str) -> None:
    print(f"[installer] {message}", flush=True)


def ensure_script_encoding() -> None:
    """makensis detects UTF-8 only via BOM; without it Chinese text is read as ACP."""
    raw = NSI_FILE.read_bytes()
    if not raw.startswith(b"\xef\xbb\xbf"):
        NSI_FILE.write_bytes(b"\xef\xbb\xbf" + raw)
        log("added UTF-8 BOM to installer.nsi")


def detect_version() -> tuple[str, tuple[int, int, int, int]]:
    """Return (display version, 4-part numeric version) for the current tree."""
    version_file = ROOT / "videocaptioner" / "_version.py"
    raw = ""
    if version_file.exists():
        match = re.search(r"__version__\s*=\s*version\s*=\s*['\"]([^'\"]+)['\"]", version_file.read_text(encoding="utf-8"))
        if match:
            raw = match.group(1)
    if not raw:
        try:
            import importlib.metadata

            raw = importlib.metadata.version("videocaptioner")
        except Exception:
            raw = "0.0.0"

    # Drop the local version (`+g<hash>`) and hatch-vcs dirty marker (`.d20260101`);
    # neither belongs in a user-facing installer name.
    display = re.sub(r"\.d\d{8}$", "", raw.split("+", 1)[0].strip()) or "0.0.0"
    numbers = [int(part) for part in re.findall(r"\d+", display)]
    numbers = (numbers + [0, 0, 0, 0])[:4]
    return display, (numbers[0], numbers[1], numbers[2], numbers[3])


def make_icon() -> Path | None:
    """Build a multi-resolution .ico from the project logo."""
    if not LOGO_SRC.exists():
        log(f"logo not found, skipping icon: {LOGO_SRC}")
        return None
    try:
        from PIL import Image
    except ImportError:
        log("Pillow unavailable, skipping icon")
        return None

    image = Image.open(LOGO_SRC).convert("RGBA")
    side = max(image.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(image, ((side - image.width) // 2, (side - image.height) // 2), image)
    canvas.save(
        ICON_FILE,
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
    )
    log(f"icon -> {ICON_FILE.relative_to(ROOT)}")
    return ICON_FILE


def make_version_info(version: str, quad: tuple[int, int, int, int]) -> list[Path]:
    """Write PyInstaller version resources so the exe shows real file properties."""
    written = []
    for target, original, description, internal in (
        (VERSION_INFO_CLI, f"{APP_NAME}.exe", f"{APP_NAME} command line interface", APP_NAME),
        (VERSION_INFO_GUI, f"{APP_NAME}-GUI.exe", f"{APP_NAME} desktop app", f"{APP_NAME}-GUI"),
    ):
        target.write_text(
            VERSION_INFO_TEMPLATE.format(
                quad=quad,
                quad_text=".".join(str(n) for n in quad),
                publisher=APP_PUBLISHER,
                description=description,
                internal=internal,
                original=original,
                app=APP_NAME,
                version=version,
            ),
            encoding="utf-8",
        )
        written.append(target)
    log(f"version resources -> {', '.join(p.name for p in written)}")
    return written


def find_makensis(explicit: str | None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("MAKENSIS"):
        candidates.append(Path(os.environ["MAKENSIS"]))
    candidates.extend(MAKENSIS_CANDIDATES)
    which = shutil.which("makensis")
    if which:
        candidates.append(Path(which))

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "makensis (NSIS) not found. Install NSIS or pass --makensis <path to makensis.exe>."
    )


def bundle_size_mb() -> float:
    if not BUNDLE_DIR.is_dir():
        return 0.0
    return sum(f.stat().st_size for f in BUNDLE_DIR.rglob("*") if f.is_file()) / 1048576


def run_makensis(makensis: Path, defines: dict[str, str], compressor: str) -> Path:
    out_file = Path(defines["OUT_FILE"])
    out_file.parent.mkdir(parents=True, exist_ok=True)

    cmd = [str(makensis), "-V3", f"-DCOMPRESSOR={compressor}"]
    for key, value in defines.items():
        cmd.append(f"-D{key}={value}")
    cmd.append(str(NSI_FILE))

    log("makensis " + " ".join(f"-D{k}={v}" for k, v in defines.items()))
    result = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True)
    output = (result.stdout or "") + (result.stderr or "")
    if output.strip():
        print(output.strip())
    if result.returncode != 0:
        raise RuntimeError(f"makensis failed with exit code {result.returncode}")
    if not out_file.exists():
        raise RuntimeError(f"installer was not produced: {out_file}")
    return out_file


# --------------------------------------------------------------------- main ---


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prep", action="store_true", help="Only generate icon + version resources, then stop")
    parser.add_argument("--makensis", help="Path to makensis.exe")
    parser.add_argument("--compressor", default="lzma", help="NSIS compressor: lzma (default), zlib, bzip2, none")
    parser.add_argument("--bundle", help="Override the bundle directory (default dist/VideoCaptioner)")
    args = parser.parse_args()

    version, quad = detect_version()
    log(f"version = {version} (resource {'/'.join(str(n) for n in quad)})")

    ensure_script_encoding()
    icon = make_icon()
    make_version_info(version, quad)

    if args.prep:
        return 0

    bundle = Path(args.bundle).resolve() if args.bundle else BUNDLE_DIR
    if not bundle.is_dir():
        raise SystemExit(
            f"Desktop bundle not found: {bundle}\n"
            "Run first: python scripts/build_desktop.py --clean"
        )
    exe_names = sorted(p.name for p in bundle.glob("*.exe"))
    log(f"bundle = {bundle} ({bundle_size_mb():.1f} MB) exe={exe_names}")

    makensis = find_makensis(args.makensis)
    log(f"makensis = {makensis}")

    display = version
    out_file = ARTIFACT_DIR / f"{APP_NAME}-{display}-windows-x64-setup.exe"

    defines = {
        "SOURCE_DIR": bundle,
        "APP_VERSION": display,
        "APP_VERSION_NUM": ".".join(str(n) for n in quad),
        "OUT_FILE": out_file,
        "LICENSE_FILE": LICENSE_FILE,
    }
    if icon:
        defines["ICON_FILE"] = icon

    out = run_makensis(makensis, defines, args.compressor)
    log(f"installer -> {out}  ({out.stat().st_size / 1048576:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
