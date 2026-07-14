"""py2app build script -- `python setup.py py2app` produces dist/GitGood.app."""
import os
import sys

from setuptools import setup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

APP = ["src/gitgood/main.py"]
ICON_PATH = "resources/icon.icns"

OPTIONS = {
    "argv_emulation": False,
    "packages": ["gitgood"],
    # _cffi_backend is a compiled extension module that PyNaCl (a PyGithub
    # dependency, for repo-secret public-key encryption we don't even use)
    # loads dynamically -- py2app's static analysis misses it, which crashes
    # the packaged app at import time even though it works fine from source.
    # keyring.backends.macOS is loaded the same dynamic way (via importlib.metadata
    # entry points), so it's missed the same way and must also be forced in.
    "includes": [
        "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets",
        "_cffi_backend", "cffi", "nacl",
        "keyring.backends.macOS",
    ],
    # Dev-only tooling that happens to be installed in this venv but is never
    # imported at runtime -- keeps the bundle from dragging in test suites.
    "excludes": ["pytest", "_pytest", "pyflakes", "py2app", "pip", "wheel"],
    "plist": {
        "CFBundleName": "GitGood",
        "CFBundleDisplayName": "GitGood",
        "CFBundleIdentifier": "com.gitgood.app",
        "CFBundleVersion": "0.1.0",
        "CFBundleShortVersionString": "0.1.0",
        "NSHighResolutionCapable": True,
    },
}

if os.path.exists(ICON_PATH):
    OPTIONS["iconfile"] = ICON_PATH

setup(
    app=APP,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
