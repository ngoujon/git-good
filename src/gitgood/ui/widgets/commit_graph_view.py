"""The centerpiece widget: a GitKraken/SourceTree-style commit graph.

Renders `graph.py`'s pure lane layout as colored columns with curved merge
lines, next to a table-like text area (SHA, ref badges + summary, author,
date) with a real header row above it. Author/date are independently
toggleable columns (`set_show_author`/`set_show_date`); `GraphColumnHeader`
and the row painter share one `_column_layout()` function so the header
labels always land above the text they describe.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractScrollArea, QMenu, QToolButton, QWidget

from gitgood.git_ops.graph import CommitGraph, GraphNode
from gitgood.ui import theme as theme_mod

ROW_HEIGHT = 28
LANE_WIDTH = 18
LANE_MARGIN = 24
DOT_RADIUS = 5
TEXT_PADDING = 12
SHA_COLUMN_WIDTH = 76
AUTHOR_COLUMN_WIDTH = 130
DATE_COLUMN_WIDTH = 90
HEADER_HEIGHT = 26
SETTINGS_COLUMN_WIDTH = 28


def _relative_date(epoch_seconds: int) -> str:
    delta = max(0, int(time.time()) - epoch_seconds)
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    if delta < 86400 * 30:
        return f"{delta // 86400}d ago"
    if delta < 86400 * 365:
        return f"{delta // (86400 * 30)}mo ago"
    return f"{delta // (86400 * 365)}y ago"


@dataclass
class _ColumnLayout:
    sha_x: int
    message_x: int
    message_w: int
    author_x: int | None
    date_x: int | None


def _column_layout(width: int, graph_width: int, show_author: bool, show_date: bool) -> _ColumnLayout:
    sha_x = graph_width + TEXT_PADDING
    message_x = sha_x + SHA_COLUMN_WIDTH
    right_x = width - TEXT_PADDING - SETTINGS_COLUMN_WIDTH
    date_x = None
    author_x = None
    if show_date:
        right_x -= DATE_COLUMN_WIDTH
        date_x = right_x
    if show_author:
        right_x -= AUTHOR_COLUMN_WIDTH
        author_x = right_x
    message_w = max(20, right_x - message_x - TEXT_PADDING)
    return _ColumnLayout(sha_x=sha_x, message_x=message_x, message_w=message_w, author_x=author_x, date_x=date_x)


class GraphColumnHeader(QWidget):
    """Column titles above CommitGraphView, plus the "which columns are
    visible" settings menu -- kept out of the per-row painting so toggling
    Author/Date doesn't need its own toolbar real estate."""

    def __init__(self, graph_view: "CommitGraphView", parent: QWidget | None = None):
        super().__init__(parent)
        self._graph_view = graph_view
        self.setFixedHeight(HEADER_HEIGHT)
        graph_view.columns_changed.connect(self.update)

        self.settings_btn = QToolButton(self)
        self.settings_btn.setText("⚙")
        self.settings_btn.setAutoRaise(True)
        self.settings_btn.setToolTip("Choose visible columns")
        self.settings_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        menu = QMenu(self.settings_btn)
        self.author_action = menu.addAction("Show Author")
        self.author_action.setCheckable(True)
        self.author_action.setChecked(graph_view.show_author)
        self.author_action.toggled.connect(graph_view.set_show_author)
        self.date_action = menu.addAction("Show Date")
        self.date_action.setCheckable(True)
        self.date_action.setChecked(graph_view.show_date)
        self.date_action.toggled.connect(graph_view.set_show_date)
        self.settings_btn.setMenu(menu)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.settings_btn.setGeometry(self.width() - SETTINGS_COLUMN_WIDTH, 0, SETTINGS_COLUMN_WIDTH, self.height())

    def paintEvent(self, event) -> None:
        theme = self._graph_view.theme
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme["toolbar_bg"]))

        col = _column_layout(self.width(), self._graph_view.graph_column_width(), self._graph_view.show_author, self._graph_view.show_date)
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(theme["text_secondary"]))

        def draw(x: int, w: int, text: str) -> None:
            painter.drawText(x, 0, w, self.height(), Qt.AlignmentFlag.AlignVCenter, text)

        draw(TEXT_PADDING, col.sha_x - TEXT_PADDING, "Graph")
        draw(col.sha_x, SHA_COLUMN_WIDTH, "SHA")
        draw(col.message_x, col.message_w, "Message")
        if col.author_x is not None:
            draw(col.author_x, AUTHOR_COLUMN_WIDTH, "Author")
        if col.date_x is not None:
            draw(col.date_x, DATE_COLUMN_WIDTH, "Date")

        painter.setPen(QColor(theme["border"]))
        painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)


class CommitGraphView(QAbstractScrollArea):
    commit_selected = Signal(str)  # sha
    columns_changed = Signal()  # lane count or column visibility changed -- header must repaint

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._graph = CommitGraph()
        self._row_by_sha: dict[str, int] = {}
        self._selected_sha: str | None = None
        self._match_shas: set[str] = set()
        self.theme = theme_mod.current_theme()
        self.show_author = True
        self.show_date = True
        self._mono_font = QFont("Menlo", 12)
        self.setFrameShape(QAbstractScrollArea.Shape.NoFrame)
        self.viewport().setMouseTracking(True)

    def refresh_theme(self) -> None:
        self.theme = theme_mod.current_theme()
        self.viewport().update()
        self.columns_changed.emit()  # header reads self.theme too and must repaint

    def _lane_color(self, index: int) -> QColor:
        colors = self.theme["lane_colors"]
        return QColor(colors[index % len(colors)])

    # ---- public API -----------------------------------------------------------

    def set_graph(self, graph: CommitGraph) -> None:
        self._graph = graph
        self._row_by_sha = {node.sha: i for i, node in enumerate(graph.nodes)}
        if self._selected_sha not in self._row_by_sha:
            self._selected_sha = None
        total_height = len(graph.nodes) * ROW_HEIGHT
        self.verticalScrollBar().setRange(0, max(0, total_height - self.viewport().height()))
        self.verticalScrollBar().setPageStep(self.viewport().height())
        self.viewport().update()
        self.columns_changed.emit()  # lane_count (and so graph_column_width) may have changed

    def get_node(self, sha: str) -> GraphNode | None:
        row = self._row_by_sha.get(sha)
        return self._graph.nodes[row] if row is not None else None

    def set_show_author(self, show: bool) -> None:
        self.show_author = show
        self.columns_changed.emit()
        self.viewport().update()

    def set_show_date(self, show: bool) -> None:
        self.show_date = show
        self.columns_changed.emit()
        self.viewport().update()

    def set_filter(self, text: str) -> list[str]:
        """Highlight commits whose summary/author/SHA match `text`; returns
        matching SHAs in display order so the caller can jump to the first one."""
        text = text.strip().lower()
        if not text:
            self._match_shas = set()
            self.viewport().update()
            return []
        matches = [
            n.sha
            for n in self._graph.nodes
            if text in n.summary.lower() or text in n.author_name.lower() or n.sha.startswith(text)
        ]
        self._match_shas = set(matches)
        self.viewport().update()
        return matches

    def select_commit(self, sha: str | None) -> None:
        self._selected_sha = sha
        self.viewport().update()

    def scroll_to_sha(self, sha: str) -> None:
        row = self._row_by_sha.get(sha)
        if row is None:
            return
        self.verticalScrollBar().setValue(row * ROW_HEIGHT - self.viewport().height() // 2)

    def graph_column_width(self) -> int:
        return LANE_MARGIN + (self._graph.lane_count + 1) * LANE_WIDTH

    def column_layout(self, width: int | None = None) -> _ColumnLayout:
        w = width if width is not None else self.viewport().width()
        return _column_layout(w, self.graph_column_width(), self.show_author, self.show_date)

    # ---- painting ---------------------------------------------------------------

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        total_height = len(self._graph.nodes) * ROW_HEIGHT
        self.verticalScrollBar().setRange(0, max(0, total_height - self.viewport().height()))
        self.verticalScrollBar().setPageStep(self.viewport().height())

    def _row_center_y(self, row: int, scroll_offset: int) -> int:
        return row * ROW_HEIGHT + ROW_HEIGHT // 2 - scroll_offset

    def paintEvent(self, event) -> None:
        theme = self.theme
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.viewport().rect(), QColor(theme["surface"]))

        scroll_offset = self.verticalScrollBar().value()
        viewport_h = self.viewport().height()
        viewport_w = self.viewport().width()
        first_row = max(0, scroll_offset // ROW_HEIGHT)
        last_row = min(len(self._graph.nodes), (scroll_offset + viewport_h) // ROW_HEIGHT + 2)

        col = self.column_layout(viewport_w)
        default_font = painter.font()
        font_metrics = QFontMetrics(default_font)
        mono_metrics = QFontMetrics(self._mono_font)

        for row in range(first_row, last_row):
            node = self._graph.nodes[row]
            y = self._row_center_y(row, scroll_offset)
            row_top = row * ROW_HEIGHT - scroll_offset

            if row % 2 == 1:
                painter.fillRect(QRectF(0, row_top, viewport_w, ROW_HEIGHT), QColor(theme["toolbar_bg"]))
            if node.sha == self._selected_sha:
                painter.fillRect(QRectF(0, row_top, viewport_w, ROW_HEIGHT), QColor(theme["selection_bg"]))
            elif node.sha in self._match_shas:
                painter.fillRect(QRectF(0, row_top, viewport_w, ROW_HEIGHT), QColor(theme["match_bg"]))

            self._paint_edges(painter, node, row, scroll_offset)

            dot_x = LANE_MARGIN + node.lane * LANE_WIDTH
            color = self._lane_color(node.color_index)
            painter.setPen(QPen(color, 2))
            painter.setBrush(color)
            painter.drawEllipse(QPointF(dot_x, y), DOT_RADIUS, DOT_RADIUS)

            painter.setFont(self._mono_font)
            painter.setPen(QColor(theme["text_secondary"]))
            painter.drawText(col.sha_x, y + mono_metrics.ascent() // 2 - 1, node.short_sha)
            painter.setFont(default_font)

            text_x = col.message_x
            message_right = col.message_x + col.message_w
            for ref in node.refs:
                badge_w = font_metrics.horizontalAdvance(ref) + 10
                if text_x + badge_w > message_right:
                    break
                badge_rect = QRectF(text_x, y - 9, badge_w, 18)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(theme["link"]))
                painter.drawRoundedRect(badge_rect, 4, 4)
                painter.setPen(QColor(theme["link_text"]))
                painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, ref)
                text_x += badge_w + 6

            painter.setPen(QColor(theme["text_primary"]))
            summary_max_w = max(20, message_right - text_x)
            summary = font_metrics.elidedText(node.summary, Qt.TextElideMode.ElideRight, summary_max_w)
            painter.drawText(text_x, y + font_metrics.ascent() // 2 - 1, summary)

            painter.setPen(QColor(theme["text_secondary"]))
            if col.author_x is not None:
                author = font_metrics.elidedText(node.author_name, Qt.TextElideMode.ElideRight, AUTHOR_COLUMN_WIDTH - TEXT_PADDING)
                painter.drawText(col.author_x, y + font_metrics.ascent() // 2 - 1, author)
            if col.date_x is not None:
                painter.drawText(col.date_x, y + font_metrics.ascent() // 2 - 1, _relative_date(node.authored_date))

        painter.setPen(QPen(QColor(theme["border"]), 1))
        for x in (col.sha_x, col.message_x, col.author_x, col.date_x):
            if x is not None:
                painter.drawLine(x - TEXT_PADDING // 2, 0, x - TEXT_PADDING // 2, viewport_h)

    def _paint_edges(self, painter: QPainter, node: GraphNode, row: int, scroll_offset: int) -> None:
        from_x = LANE_MARGIN + node.lane * LANE_WIDTH
        from_y = self._row_center_y(row, scroll_offset)

        for edge in self._graph.edges.get(node.sha, []):
            if edge.to_lane is None:
                continue  # truncated/shallow history -- nothing to draw down to
            parent_row = self._row_by_sha.get(edge.parent_sha)
            if parent_row is None:
                continue
            to_x = LANE_MARGIN + edge.to_lane * LANE_WIDTH
            to_y = self._row_center_y(parent_row, scroll_offset)

            pen_color = self._lane_color(node.color_index)
            painter.setPen(QPen(pen_color, 2))
            if from_x == to_x:
                painter.drawLine(QPointF(from_x, from_y), QPointF(to_x, to_y))
            else:
                path = QPainterPath(QPointF(from_x, from_y))
                mid_y = (from_y + to_y) / 2
                path.cubicTo(QPointF(from_x, mid_y), QPointF(to_x, mid_y), QPointF(to_x, to_y))
                painter.drawPath(path)

    # ---- mouse interaction ------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        scroll_offset = self.verticalScrollBar().value()
        row = (event.position().y() + scroll_offset) // ROW_HEIGHT
        row = int(row)
        if 0 <= row < len(self._graph.nodes):
            node = self._graph.nodes[row]
            self._selected_sha = node.sha
            self.viewport().update()
            self.commit_selected.emit(node.sha)
        super().mousePressEvent(event)
