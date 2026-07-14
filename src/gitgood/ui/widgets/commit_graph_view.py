"""The centerpiece widget: a GitKraken/SourceTree-style commit graph.

Renders `graph.py`'s pure lane layout as colored columns with curved merge
lines, and a synced text area (short SHA, ref badges, summary, author, date)
to the right -- all in one custom-painted, scrollable widget.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractScrollArea, QWidget

from gitgood.git_ops.graph import CommitGraph, GraphNode
from gitgood.ui import theme as theme_mod

ROW_HEIGHT = 28
LANE_WIDTH = 18
LANE_MARGIN = 24
DOT_RADIUS = 5
TEXT_PADDING = 12


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


class CommitGraphView(QAbstractScrollArea):
    commit_selected = Signal(str)  # sha

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._graph = CommitGraph()
        self._row_by_sha: dict[str, int] = {}
        self._selected_sha: str | None = None
        self._match_shas: set[str] = set()
        self._theme = theme_mod.current_theme()
        self.setFrameShape(QAbstractScrollArea.Shape.NoFrame)
        self.viewport().setMouseTracking(True)

    def refresh_theme(self) -> None:
        self._theme = theme_mod.current_theme()
        self.viewport().update()

    def _lane_color(self, index: int) -> QColor:
        colors = self._theme["lane_colors"]
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

    # ---- painting ---------------------------------------------------------------

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        total_height = len(self._graph.nodes) * ROW_HEIGHT
        self.verticalScrollBar().setRange(0, max(0, total_height - self.viewport().height()))
        self.verticalScrollBar().setPageStep(self.viewport().height())

    def _row_center_y(self, row: int, scroll_offset: int) -> int:
        return row * ROW_HEIGHT + ROW_HEIGHT // 2 - scroll_offset

    def paintEvent(self, event) -> None:
        theme = self._theme
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.viewport().rect(), QColor(theme["surface"]))

        scroll_offset = self.verticalScrollBar().value()
        viewport_h = self.viewport().height()
        first_row = max(0, scroll_offset // ROW_HEIGHT)
        last_row = min(len(self._graph.nodes), (scroll_offset + viewport_h) // ROW_HEIGHT + 2)

        graph_width = self.graph_column_width()
        font_metrics = QFontMetrics(painter.font())

        for row in range(first_row, last_row):
            node = self._graph.nodes[row]
            y = self._row_center_y(row, scroll_offset)
            row_top = row * ROW_HEIGHT - scroll_offset

            if node.sha == self._selected_sha:
                painter.fillRect(QRectF(0, row_top, self.viewport().width(), ROW_HEIGHT), QColor(theme["selection_bg"]))
            elif node.sha in self._match_shas:
                painter.fillRect(QRectF(0, row_top, self.viewport().width(), ROW_HEIGHT), QColor(theme["match_bg"]))

            self._paint_edges(painter, node, row, scroll_offset)

            dot_x = LANE_MARGIN + node.lane * LANE_WIDTH
            color = self._lane_color(node.color_index)
            painter.setPen(QPen(color, 2))
            painter.setBrush(color)
            painter.drawEllipse(QPointF(dot_x, y), DOT_RADIUS, DOT_RADIUS)

            text_x = graph_width + TEXT_PADDING
            painter.setPen(QColor(theme["text_primary"]))
            painter.drawText(text_x, y + font_metrics.ascent() // 2 - 1, node.short_sha)

            text_x += font_metrics.horizontalAdvance(node.short_sha) + 12
            for ref in node.refs:
                badge_text = ref
                badge_w = font_metrics.horizontalAdvance(badge_text) + 10
                badge_rect = QRectF(text_x, y - 9, badge_w, 18)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(theme["link"]))
                painter.drawRoundedRect(badge_rect, 4, 4)
                painter.setPen(QColor(theme["link_text"]))
                painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)
                text_x += badge_w + 6

            painter.setPen(QColor(theme["text_primary"]))
            summary_max_w = max(50, self.viewport().width() - text_x - 220)
            summary = font_metrics.elidedText(node.summary, Qt.TextElideMode.ElideRight, summary_max_w)
            painter.drawText(text_x, y + font_metrics.ascent() // 2 - 1, summary)

            meta = f"{node.author_name} · {_relative_date(node.authored_date)}"
            painter.setPen(QColor(theme["text_secondary"]))
            painter.drawText(
                self.viewport().width() - 210,
                y + font_metrics.ascent() // 2 - 1,
                210 - TEXT_PADDING,
                ROW_HEIGHT,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                meta,
            )

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
