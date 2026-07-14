from __future__ import annotations

import sys

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from gitgood.ui import theme
from gitgood.ui.app_window import AppWindow


def run(repo_path: str | None = None) -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("GitGood")

    def apply_theme() -> None:
        app.setStyleSheet(theme.build_stylesheet(theme.current_theme()))

    apply_theme()
    style_hints = QGuiApplication.styleHints()
    if hasattr(style_hints, "colorSchemeChanged"):
        style_hints.colorSchemeChanged.connect(lambda _scheme: apply_theme())

    window = AppWindow()

    if hasattr(style_hints, "colorSchemeChanged"):
        def refresh_open_tabs(_scheme):
            for tab in window.all_repo_tabs():
                tab.graph_view.refresh_theme()
                tab.diff_view.refresh_theme()

        style_hints.colorSchemeChanged.connect(refresh_open_tabs)

    if repo_path:
        window.open_repo_path(repo_path)

    window.show()
    return app.exec()
