"""Light/dark theme that follows the macOS system appearance.

Both palettes come from the validated dataviz reference palette (light and
dark columns of the same 8 hues -- fixed order, never re-sorted or cycled).
Everything the UI paints (QSS *and* the hand-drawn commit graph) reads colors
from `current_theme()` rather than hardcoding them, so switching macOS
appearance while the app is running just re-derives the same dict.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPalette

LIGHT = {
    "surface": "#ffffff",
    "page_plane": "#f9f9f7",
    "toolbar_bg": "#f6f8fa",
    "text_primary": "#24292f",
    "text_secondary": "#57606a",
    "border": "#d0d7de",
    "accent": "#2da44e",
    "accent_hover": "#2c974b",
    "accent_disabled": "#94d3a2",
    "link": "#0969da",
    "link_text": "#ffffff",
    "selection_bg": "#ddf4ff",
    "match_bg": "#fff8c5",
    "diff_add_bg": "#ccffd8",
    "diff_del_bg": "#ffd7d5",
    "lane_colors": [
        "#2a78d6", "#1baf7a", "#eda100", "#008300",
        "#4a3aa7", "#e34948", "#e87ba4", "#eb6834",
    ],
}

DARK = {
    "surface": "#1a1a19",
    "page_plane": "#0d0d0d",
    "toolbar_bg": "#22221f",
    "text_primary": "#ffffff",
    "text_secondary": "#c3c2b7",
    "border": "#383835",
    "accent": "#2da44e",
    "accent_hover": "#3fbb5e",
    "accent_disabled": "#2c5c37",
    "link": "#3987e5",
    "link_text": "#ffffff",
    "selection_bg": "#173c52",
    "match_bg": "#3d3419",
    "diff_add_bg": "#1b4721",
    "diff_del_bg": "#4c1e1e",
    "lane_colors": [
        "#3987e5", "#199e70", "#c98500", "#008300",
        "#9085e9", "#e66767", "#d55181", "#d95926",
    ],
}


def is_dark_mode() -> bool:
    style_hints = QGuiApplication.styleHints()
    scheme = getattr(style_hints, "colorScheme", None)
    if scheme is not None:
        value = scheme()
        if value != Qt.ColorScheme.Unknown:
            return value == Qt.ColorScheme.Dark
    # Fallback for environments where colorScheme() isn't reporting yet.
    return QGuiApplication.palette().color(QPalette.ColorRole.Window).lightness() < 128


def current_theme() -> dict:
    return DARK if is_dark_mode() else LIGHT


def avatar_color(name: str) -> str:
    """Deterministic color for a repo's sidebar avatar, picked from the same
    validated palette as the commit graph lanes so it never clashes with the
    rest of the UI. Uses the light-theme swatch order as the canonical
    source -- both palettes share the same hue sequence, just different
    lightness, so the mapping stays stable across theme switches."""
    colors = LIGHT["lane_colors"]
    return colors[sum(name.encode("utf-8")) % len(colors)]


def build_stylesheet(theme: dict) -> str:
    return f"""
QMainWindow, QWidget {{
    background-color: {theme["page_plane"]};
    color: {theme["text_primary"]};
    font-size: 13px;
}}
QToolBar {{
    background-color: {theme["toolbar_bg"]};
    border-bottom: 1px solid {theme["border"]};
    padding: 6px;
    spacing: 8px;
}}
/* General buttons (Commit, dialog primary actions, etc.) stay solid-accent
   "primary" buttons. Toolbar buttons are restyled to a flat/neutral look
   right below so the persistent global toolbar doesn't read as a wall of
   solid green -- that's the main lever for a calmer, more modern look. */
QPushButton {{
    background-color: {theme["accent"]};
    color: white;
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: {theme["accent_hover"]};
}}
QPushButton:disabled {{
    background-color: {theme["accent_disabled"]};
}}
QToolBar QPushButton {{
    background-color: transparent;
    color: {theme["text_primary"]};
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 6px 12px;
    font-weight: 500;
}}
QToolBar QPushButton:hover {{
    background-color: {theme["border"]};
}}
QToolBar QPushButton:disabled {{
    color: {theme["text_secondary"]};
}}
QListWidget, QTreeWidget, QTableWidget, QLineEdit, QPlainTextEdit, QTextEdit {{
    background-color: {theme["surface"]};
    color: {theme["text_primary"]};
    border: 1px solid {theme["border"]};
    border-radius: 9px;
}}
QSplitter::handle {{
    background-color: {theme["border"]};
}}
QStatusBar {{
    background-color: {theme["toolbar_bg"]};
    border-top: 1px solid {theme["border"]};
}}
QTabWidget::pane {{
    background-color: {theme["surface"]};
    border: 1px solid {theme["border"]};
    border-radius: 9px;
    top: -1px;
}}
QTabBar::tab {{
    background-color: {theme["page_plane"]};
    color: {theme["text_secondary"]};
    border: 1px solid {theme["border"]};
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 7px 14px;
    margin-right: 3px;
}}
QTabBar::tab:selected {{
    background-color: {theme["surface"]};
    color: {theme["text_primary"]};
    font-weight: 600;
}}
QTabBar::tab:hover:!selected {{
    color: {theme["text_primary"]};
}}
QTabBar::close-button {{
    subcontrol-position: right;
}}
QWidget#repoSidebar {{
    background-color: {theme["toolbar_bg"]};
    border-right: 1px solid {theme["border"]};
}}
QListWidget#repoList {{
    background-color: transparent;
    border: none;
    outline: none;
    padding: 4px;
}}
QListWidget#repoList::item {{
    border-radius: 8px;
    padding: 2px;
    margin-bottom: 2px;
    border-left: 3px solid transparent;
}}
QListWidget#repoList::item:hover {{
    background-color: {theme["border"]};
}}
QListWidget#repoList::item:selected {{
    background-color: {theme["selection_bg"]};
    border-left: 3px solid {theme["accent"]};
}}
QPushButton#sidebarIconButton {{
    background-color: transparent;
    color: {theme["text_primary"]};
    border: 1px solid {theme["border"]};
    border-radius: 6px;
    padding: 6px;
    font-weight: 500;
}}
QPushButton#sidebarIconButton:hover {{
    background-color: {theme["border"]};
}}
QPushButton#repoCloseButton {{
    background-color: transparent;
    color: {theme["text_secondary"]};
    border: none;
    border-radius: 4px;
    padding: 2px 6px;
    font-weight: 700;
}}
QPushButton#repoCloseButton:hover {{
    background-color: {theme["diff_del_bg"]};
    color: {theme["text_primary"]};
}}
QLabel#repoBadge {{
    background-color: {theme["accent"]};
    color: white;
    border-radius: 8px;
    padding: 1px 6px;
    font-size: 11px;
    font-weight: 700;
}}
"""
