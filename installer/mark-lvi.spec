# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for MARK LVI (Linux, one-folder build).

Code is bundled into _internal/; data folders (actions/, plugins/, config/,
assets/, …) are copied NEXT TO the executable by build_bundle.sh, because the
app resolves BASE_DIR to the executable's directory when frozen.
"""
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

hiddenimports = [
    # UI / audio / media
    "PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets", "PyQt6.QtMultimedia",
    "PyQt6.QtMultimediaWidgets", "PyQt6.QtNetwork", "PyQt6.QtDBus",
    "sounddevice", "numpy", "PIL", "PIL.Image", "cv2", "mss",
    # Gemini / LLM
    "google.genai", "google.genai.types", "httpx", "requests",
    # Web / automation
    "bs4", "playwright.sync_api", "pyautogui", "pyperclip",
    "Xlib", "Xlib.xauth",
    # Documents / system
    "psutil", "send2trash", "pptx", "pdfplumber", "PyPDF2", "docx",
    "openpyxl", "pynvml", "dnspython", "joblib",
    # Dashboard
    "fastapi", "uvicorn", "uvicorn.logging", "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on", "cryptography", "multipart", "qrcode",
    "qrcode.image.pil",
    # Plugin extras
    "googleapiclient.discovery", "google_auth_oauthlib.flow",
    "tinytuya", "paho.mqtt.client", "youtube_transcript_api",
    "pygetwindow", "ddgs", "yt_dlp",
    # terminal-UI fallback action
    "curses", "_curses",
    # 3D workshop viewport + arc reactor widget (also pulled in via the core
    # submodule sweep — listed explicitly so the egl platform plugin comes too)
    "OpenGL", "OpenGL.GL", "OpenGL.GLU", "OpenGL_accelerate",
    "OpenGL.platform.egl",
]

hiddenimports += collect_submodules("yt_dlp")
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("google.genai")
# App packages: actions/plugins are loaded from disk at runtime and import
# these by name, so every app module must be bundled even if main.py never
# imports it statically.
for pkg in ("core", "config", "memory", "dashboard", "providers"):
    hiddenimports += collect_submodules(pkg)

datas = [("../dashboard/static", "dashboard/static")]
datas += collect_data_files("playwright")
datas += collect_data_files("sounddevice")

a = Analysis(
    ["../main.py"],
    pathex=[".."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "torch", "mediapipe", "pandas", "matplotlib", "openwakeword",
        "faster_whisper", "piper", "piper_tts", "pydantic_ai",
        # dev-only geometry/video tooling (needs torch anyway, which is
        # excluded — these only serve scripts/, never the runtime app)
        "open3d", "trimesh", "av", "pytorch3d",
        "tests", "demos", "apps", "tkinter", "pytest",
        # one Qt binding only — PyQt5/PySide* are stray transitive installs
        "PyQt5", "PySide2", "PySide6", "PyQt6.Qt5Compat",
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
    [],
    exclude_binaries=True,
    name="mark-lvi",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon="../config/jarvis.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="mark-lvi",
)
