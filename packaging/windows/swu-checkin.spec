# Build only on Windows x64, using scripts/windows/build.ps1.
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH).parents[1]
datas = [
    (str(root / "LICENSE"), "."),
    (str(root / "build/windows/metadata"), "build-info"),
]
binaries = []
hiddenimports = ["msvcrt", "tkinter", "tkinter.ttk", "tkinter.messagebox", "_tkinter"]
for package in ("ddddocr", "onnxruntime", "cv2", "numpy", "tzdata", "certifi"):
    package_data, package_binaries, package_imports = collect_all(
        package,
        include_py_files=False,
        filter_submodules=lambda name: not any(part in {"tests", "test", "__pycache__"} for part in name.split(".")),
        exclude_datas=["**/tests/**", "**/test/**", "**/__pycache__/**"],
    )
    datas += package_data
    binaries += package_binaries
    hiddenimports += package_imports
datas += copy_metadata("swu-checkin", recursive=True)

a = Analysis(
    [str(root / "packaging/windows/entrypoint.py")],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "mypy", "ruff"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SWUCheckin",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=True,
    uac_admin=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="SWUCheckin")
