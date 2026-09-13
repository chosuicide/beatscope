# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the self-contained Windows Studio."""
from PyInstaller.utils.hooks import collect_data_files, copy_metadata
from pathlib import Path


ROOT = Path(SPECPATH).resolve().parent
datas = collect_data_files("beatscope")
for distribution in ("librosa", "soundfile", "numpy", "scipy", "numba", "llvmlite"):
    datas += copy_metadata(distribution)

analysis = Analysis(
    [str(ROOT / "beatscope" / "desktop.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # The desktop build intentionally ships the lightweight analyser. GPU
    # Demucs remains available from the Python package, but pulling PyTorch
    # into the portable Studio would add gigabytes for a path the UI does not
    # expose.
    excludes=[
        "torch", "demucs", "pytest", "matplotlib", "IPython", "notebook", "jupyter",
        "pandas", "openpyxl", "sqlalchemy", "psycopg", "psycopg2", "sklearn",
    ],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="Beathi Studio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Keep a small console visible so the user can stop the local Studio by
    # closing it. A hidden process with no tray icon is not a usable lifecycle.
    console=True,
)
coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="Beathi Studio",
)
