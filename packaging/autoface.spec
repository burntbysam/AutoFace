# PyInstaller spec for AutoFace.
#
# Build a Windows executable ON WINDOWS (PyInstaller does not cross-compile):
#     pip install -r requirements.txt pyinstaller
#     pyinstaller packaging/autoface.spec
# The result is dist/AutoFace.exe -- a single file the shop can copy anywhere.

from pathlib import Path

block_cipher = None

ROOT = Path(SPECPATH).resolve().parent

# VERSION ships inside the bundle so the updater can compare against it.
# build_info.json is written by CI just before the build; a local build simply
# has no stamp and reports itself as a dev build.
datas = [(str(ROOT / "VERSION"), ".")]
if (ROOT / "build_info.json").is_file():
    datas.append((str(ROOT / "build_info.json"), "."))

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    # The GUI and CLI are imported lazily from __main__; the COM layer is
    # imported lazily from the workers. Name them so PyInstaller bundles them.
    hiddenimports=[
        "autoface.gui.app",
        "autoface.cli",
        "autoface.inventor.com",
        "autoface.inventor.scan",
        "autoface.inventor.export",
        "autoface.inventor.probes",
        "win32com",
        "win32com.client",
        "win32com.client.dynamic",
        "pythoncom",
        "pywintypes",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Qt modules the app never touches; excluding them roughly halves the bundle.
    excludes=[
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuick3D",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtMultimedia",
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
    ],
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
    name="AutoFace",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    # Windowed: no console flashes up behind the GUI.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
