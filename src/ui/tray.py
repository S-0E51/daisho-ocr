"""
System Tray - Tray icon and context menu management.
"""

from __future__ import annotations
import os
from typing import Callable, Dict, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QBrush, QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from ..ocr.manager import OCREngine, get_engine_name
from ..utils import BASE_DIR
from ..utils.logger import log_warning

_ICON_PATH = os.path.join(BASE_DIR, "assets", "tray_icon.ico")
_TOOLTIP_TITLE = "代書 - Japanese OCR"
_READY_BADGE_COLOR = QColor("#2f80ff")
_BUSY_BADGE_COLOR = QColor("#f2c94c")
_BADGE_OUTLINE_COLOR = QColor(22, 24, 28, 210)

TRAY_STATUS_READY = "ready"
TRAY_STATUS_BUSY = "busy"


class TrayManager:
    """Manages the system tray icon, menu, and interactions."""

    def __init__(
        self,
        parent,
        on_show_window: Callable,
        on_show_overlay: Callable,
        on_hide_overlay: Callable,
        on_show_japreader: Callable,
        on_hide_japreader: Callable,
        on_settings: Callable,
        on_reload: Callable,
        on_quit: Callable,
        on_engine_selected: Callable,
        on_tray_activated: Callable,
    ) -> None:
        self._parent = parent
        self._tray_icon: Optional[QSystemTrayIcon] = None
        self._engine_actions: Dict[OCREngine, QAction] = {}
        self._engine_menu: Optional[QMenu] = None
        self._japreader_menu: Optional[QMenu] = None
        self._japreader_status_action: Optional[QAction] = None
        self._show_japreader_action: Optional[QAction] = None
        self._hide_japreader_action: Optional[QAction] = None
        self._base_icon = self._create_icon()
        self._status = TRAY_STATUS_BUSY
        self._status_detail = "OCR model not ready"

        parent.setWindowIcon(self._create_status_icon(self._status))

        if not QSystemTrayIcon.isSystemTrayAvailable():
            log_warning("System tray not available")
            return

        icon = self._create_status_icon(self._status)
        self._tray_icon = QSystemTrayIcon(icon, parent)
        self._tray_icon.setToolTip(self._build_tooltip())

        menu = QMenu()

        show_action = menu.addAction("Show Window")
        show_action.triggered.connect(on_show_window)

        show_overlay_action = menu.addAction("Show Overlay")
        show_overlay_action.triggered.connect(on_show_overlay)

        hide_overlay_action = menu.addAction("Hide Overlay")
        hide_overlay_action.triggered.connect(on_hide_overlay)

        menu.addSeparator()

        self._engine_menu = menu.addMenu("OCR Engine")
        self._setup_engine_menu(on_engine_selected)

        self._japreader_menu = menu.addMenu("japReader")
        self._japreader_status_action = self._japreader_menu.addAction(
            "Status: Unavailable"
        )
        self._japreader_status_action.setEnabled(False)
        self._japreader_menu.addSeparator()
        self._show_japreader_action = self._japreader_menu.addAction(
            "Show japReader"
        )
        self._show_japreader_action.triggered.connect(on_show_japreader)
        self._hide_japreader_action = self._japreader_menu.addAction(
            "Hide japReader"
        )
        self._hide_japreader_action.triggered.connect(on_hide_japreader)
        self.update_japreader_status(
            "Unavailable",
            can_show=False,
            can_hide=False,
        )

        menu.addSeparator()

        settings_action = menu.addAction("Settings")
        settings_action.triggered.connect(on_settings)

        menu.addSeparator()

        reload_action = menu.addAction("Reload")
        reload_action.triggered.connect(on_reload)

        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(on_quit)

        self._tray_icon.setContextMenu(menu)
        self._tray_icon.activated.connect(on_tray_activated)
        self._tray_icon.show()

    def _create_icon(self) -> QIcon:
        """Load the tray icon from assets, falling back to a generated one."""
        if os.path.isfile(_ICON_PATH):
            icon = QIcon(_ICON_PATH)
            if not icon.isNull():
                return icon
            log_warning(f"Failed to load tray icon from {_ICON_PATH}, using fallback")

        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setBrush(QBrush(QColor(0, 255, 0)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(8, 8, 48, 48)
        painter.end()
        return QIcon(pixmap)

    def _create_status_icon(self, status: str) -> QIcon:
        """Create the tray icon with a small status badge."""
        pixmap = self._base_icon.pixmap(64, 64)
        if pixmap.isNull():
            return self._base_icon

        self._draw_status_badge(pixmap, status)
        return QIcon(pixmap)

    def _draw_status_badge(self, pixmap: QPixmap, status: str) -> None:
        """Draw a ready/loading status badge in the top-right corner."""
        size = min(pixmap.width(), pixmap.height())
        diameter = max(6, int(size * 0.32))
        margin = max(2, int(size * 0.05))
        outline_width = max(1, int(size * 0.04))
        x = pixmap.width() - diameter - margin
        y = margin
        color = _READY_BADGE_COLOR if status == TRAY_STATUS_READY else _BUSY_BADGE_COLOR

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QBrush(color))
        painter.setPen(QPen(_BADGE_OUTLINE_COLOR, outline_width))
        painter.drawEllipse(x, y, diameter, diameter)
        painter.end()

    def _build_tooltip(self) -> str:
        if self._status_detail:
            return f"{_TOOLTIP_TITLE}\n{self._status_detail}"
        if self._status == TRAY_STATUS_READY:
            return f"{_TOOLTIP_TITLE}\nReady"
        return f"{_TOOLTIP_TITLE}\nLoading or needs attention"

    def _setup_engine_menu(self, on_engine_selected: Callable) -> None:
        """Set up the OCR engine submenu."""
        self._engine_menu.clear()
        self._engine_actions.clear()

        for engine in OCREngine:
            name = get_engine_name(engine)
            action = self._engine_menu.addAction(name)
            action.setCheckable(True)
            self._engine_actions[engine] = action
            action.triggered.connect(lambda checked, e=engine: on_engine_selected(e))

    def update_engine_check(self, current_engine: OCREngine) -> None:
        """Update checkmarks in engine menu."""
        for eng, action in self._engine_actions.items():
            action.setChecked(eng == current_engine)

    def update_status(self, status: str, detail: str = "") -> None:
        """Update the tray badge and tooltip for model readiness."""
        normalized_status = TRAY_STATUS_READY if status == TRAY_STATUS_READY else TRAY_STATUS_BUSY
        self._status = normalized_status
        self._status_detail = detail.strip()
        icon = self._create_status_icon(normalized_status)

        self._parent.setWindowIcon(icon)
        if self._tray_icon:
            self._tray_icon.setIcon(icon)
            self._tray_icon.setToolTip(self._build_tooltip())

    def update_japreader_status(
        self,
        label: str,
        *,
        can_show: bool,
        can_hide: bool,
    ) -> None:
        """Update the managed companion status and available window actions."""
        if self._japreader_status_action is not None:
            self._japreader_status_action.setText(f"Status: {label}")
        if self._show_japreader_action is not None:
            self._show_japreader_action.setEnabled(bool(can_show))
        if self._hide_japreader_action is not None:
            self._hide_japreader_action.setEnabled(bool(can_hide))

    def show_message(self, title: str, message: str, duration: int = 2000) -> None:
        """Show a tray notification."""
        if self._tray_icon:
            self._tray_icon.showMessage(
                title, message,
                QSystemTrayIcon.MessageIcon.Information,
                duration
            )

    @property
    def is_visible(self) -> bool:
        return self._tray_icon is not None and self._tray_icon.isVisible()

    def hide(self) -> None:
        if self._tray_icon:
            self._tray_icon.hide()
