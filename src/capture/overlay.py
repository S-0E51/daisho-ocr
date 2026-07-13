"""
Capture Overlay - Transparent, frameless, always-on-top window for screen region selection.

Features red border, black semi-transparent interior, drag/resize,
and hotkey toggle button.
"""

from __future__ import annotations
import os
from typing import Optional, Tuple, TYPE_CHECKING
from enum import Enum, auto
from PyQt6.QtWidgets import QMainWindow, QWidget, QPushButton, QFrame, QApplication
from PyQt6.QtCore import Qt, QPoint, QRect, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QGuiApplication, QPixmap, QShortcut, QKeySequence
from PIL import Image

from ..utils.logger import log_info, log_debug, log_error, log_warning

_CAPTURE_BACKEND = os.environ.get("DAISHO_CAPTURE_BACKEND", "qt").strip().lower()

try:
    import dxcam
    DXCAM_AVAILABLE = _CAPTURE_BACKEND in {"dxcam", "auto"}
except ImportError:
    DXCAM_AVAILABLE = False

if TYPE_CHECKING:
    from PyQt6.QtGui import QMouseEvent


class ResizeEdge(Enum):
    """Edges and corners for resize detection."""
    NONE = auto()
    TOP = auto()
    BOTTOM = auto()
    LEFT = auto()
    RIGHT = auto()
    TOP_LEFT = auto()
    TOP_RIGHT = auto()
    BOTTOM_LEFT = auto()
    BOTTOM_RIGHT = auto()


class CaptureWindow(QMainWindow):
    """
    Transparent, frameless overlay window for screen region capture.

    - Red border (2px) around the window
    - Black semi-transparent interior
    - Toggle button in top-right corner (red = active, yellow = paused)
    - Draggable from interior, resizable from edges/corners
    """

    captureCompleted = pyqtSignal(object)  # Emits PIL Image
    geometryChanged = pyqtSignal(QRect)
    overlayVisibilityChanged = pyqtSignal(bool)
    captureAvailabilityChanged = pyqtSignal(bool)

    BORDER_WIDTH = 2
    RESIZE_MARGIN = 8
    MIN_SIZE = 35
    OVERLAY_ALPHA = 0.25
    DEFAULT_CAPTURE_HIDE_DELAY_MS = 120
    MIN_CAPTURE_HIDE_DELAY_MS = 30
    MAX_CAPTURE_HIDE_DELAY_MS = 500
    GEOMETRY_HISTORY_LIMIT = 20

    BORDER_COLOR = QColor(255, 0, 0)
    INTERIOR_COLOR = QColor(0, 0, 0)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._dragging = False
        self._resizing = False
        self._drag_start: Optional[QPoint] = None
        self._interaction_start_geometry: Optional[QRect] = None
        self._geometry_history: list[QRect] = []
        self._resize_edge = ResizeEdge.NONE
        self._hotkey_enabled = True
        self._capture_in_progress = False
        self._capture_hide_delay_ms = self.DEFAULT_CAPTURE_HIDE_DELAY_MS
        self._restore_after_capture = False
        self._pending_capture_rect: Optional[Tuple[int, int, int, int]] = None
        self._is_closing = False
        self._suppress_hide_event = False
        self._suppress_show_event = False
        self._dxcam_instance = None
        self._capture_timer = QTimer(self)
        self._capture_timer.setSingleShot(True)
        self._capture_timer.timeout.connect(self._run_pending_capture)

        if DXCAM_AVAILABLE:
            try:
                self._dxcam_instance = dxcam.create(output_color="BGRA")
            except Exception as e:
                log_warning(f"Failed to initialize DXcam fast-capture path: {e}")
                self._dxcam_instance = None

        self._setup_window()
        self._setup_ui()

    def _setup_window(self) -> None:
        """Configure window flags and attributes for transparency."""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setWindowOpacity(self.OVERLAY_ALPHA)
        self.setMinimumSize(self.MIN_SIZE, self.MIN_SIZE)
        self.setGeometry(100, 100, 300, 50)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setStyleSheet("background-color: red;")

    def _setup_ui(self) -> None:
        """Set up black interior frame and toggle button."""
        central = QWidget(self)
        central.setMouseTracking(True)
        central.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setCentralWidget(central)

        self._interior = QFrame(central)
        self._interior.setStyleSheet("background-color: black; border: 1px solid black;")
        self._interior.setMouseTracking(True)
        self._interior.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

        self._toggle_btn = QPushButton("停", self)
        self._toggle_btn.setFixedSize(24, 24)
        self._toggle_btn.clicked.connect(self._toggle_hotkey)
        self._toggle_btn.setStyleSheet(
            self._toggle_btn_style("red", "white", "#cc0000")
        )

        self._undo_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self)
        self._undo_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._undo_shortcut.activated.connect(self._undo_geometry_change)

        self._update_interior_geometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_interior_geometry()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._suppress_show_event:
            self._suppress_show_event = False
            return
        self.overlayVisibilityChanged.emit(True)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        if self._suppress_hide_event:
            self._suppress_hide_event = False
            return
        self.overlayVisibilityChanged.emit(False)

    def _update_interior_geometry(self) -> None:
        """Update interior frame and button positions."""
        margin = self.BORDER_WIDTH
        self._interior.setGeometry(
            margin, margin,
            self.width() - 2 * margin,
            self.height() - 2 * margin
        )

        btn_margin = 5
        self._toggle_btn.move(
            self.width() - self._toggle_btn.width() - btn_margin,
            btn_margin
        )
        self._toggle_btn.raise_()

    @staticmethod
    def _toggle_btn_style(bg: str, fg: str, hover_bg: str) -> str:
        """Generate stylesheet for the toggle button."""
        return f"""
            QPushButton {{
                background-color: {bg};
                color: {fg};
                border: none;
                font-weight: bold;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
            }}
        """

    def _toggle_hotkey(self) -> None:
        """Toggle the hotkey capture on/off."""
        self._hotkey_enabled = not self._hotkey_enabled

        if self._hotkey_enabled:
            self._toggle_btn.setStyleSheet(
                self._toggle_btn_style("red", "white", "#cc0000")
            )
            log_debug("Hotkey capture active")
        else:
            self._toggle_btn.setStyleSheet(
                self._toggle_btn_style("yellow", "black", "#cccc00")
            )
            log_debug("Hotkey capture paused")
        self.captureAvailabilityChanged.emit(self._hotkey_enabled)

    @property
    def hotkey_enabled(self) -> bool:
        return self._hotkey_enabled

    @hotkey_enabled.setter
    def hotkey_enabled(self, value: bool) -> None:
        if value != self._hotkey_enabled:
            self._toggle_hotkey()

    @property
    def capture_in_progress(self) -> bool:
        return self._capture_in_progress

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return

        self._focus_overlay()
        pos = event.position().toPoint()
        edge = self._get_resize_edge(pos)

        if edge != ResizeEdge.NONE:
            self._begin_geometry_interaction()
            self._resizing = True
            self._resize_edge = edge
        else:
            self._begin_geometry_interaction()
            self._dragging = True
            self._drag_start = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging and self._drag_start is not None:
            new_pos = event.globalPosition().toPoint() - self._drag_start
            self.move(new_pos)
        elif self._resizing:
            self._do_resize(event.globalPosition().toPoint())
        else:
            pos = event.position().toPoint()
            edge = self._get_resize_edge(pos)
            self._update_cursor(edge)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._dragging or self._resizing:
                self._finalize_geometry_interaction()

            self._dragging = False
            self._resizing = False
            self._drag_start = None
            self._interaction_start_geometry = None
            self._resize_edge = ResizeEdge.NONE

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Undo):
            self._undo_geometry_change()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
            return
        super().keyPressEvent(event)

    def _focus_overlay(self) -> None:
        """Ensure the overlay can receive keyboard shortcuts."""
        self.activateWindow()
        self.raise_()
        self.setFocus(Qt.FocusReason.MouseFocusReason)

    def focus_for_input(self) -> None:
        """Focus the overlay so follow-up key presses do not hit another app."""
        self._focus_overlay()

    def _begin_geometry_interaction(self) -> None:
        """Remember the current geometry before a drag or resize begins."""
        if self._interaction_start_geometry is None:
            self._interaction_start_geometry = QRect(self.geometry())

    def _finalize_geometry_interaction(self) -> None:
        """Store the previous geometry after a completed drag or resize."""
        if self._interaction_start_geometry is None:
            return

        current_geometry = QRect(self.geometry())
        if current_geometry != self._interaction_start_geometry:
            self._push_geometry_history(self._interaction_start_geometry)
            self.geometryChanged.emit(current_geometry)

    def _push_geometry_history(self, geometry: QRect) -> None:
        """Push a geometry entry onto the undo stack."""
        if self._geometry_history and self._geometry_history[-1] == geometry:
            return

        self._geometry_history.append(QRect(geometry))
        if len(self._geometry_history) > self.GEOMETRY_HISTORY_LIMIT:
            self._geometry_history.pop(0)

    def _undo_geometry_change(self) -> None:
        """Restore the previous overlay position and size."""
        if self._dragging or self._resizing:
            log_debug("Ignoring overlay undo while drag/resize is in progress")
            return

        if not self._geometry_history:
            log_debug("Overlay undo requested but no geometry history is available")
            return

        previous_geometry = self._geometry_history.pop()
        self.setGeometry(previous_geometry)
        self.geometryChanged.emit(QRect(self.geometry()))
        self._focus_overlay()
        log_debug(
            "Overlay geometry restored to "
            f"{previous_geometry.x()},{previous_geometry.y()} "
            f"{previous_geometry.width()}x{previous_geometry.height()}"
        )

    def center_on_global_point(self, global_pos: QPoint) -> bool:
        """Center the overlay on a screen point while keeping it fully visible."""
        screen = QGuiApplication.screenAt(global_pos)
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            log_warning("No screen available to center overlay")
            return False

        screen_geometry = screen.geometry()
        current_geometry = QRect(self.geometry())

        max_x = screen_geometry.x() + max(0, screen_geometry.width() - current_geometry.width())
        max_y = screen_geometry.y() + max(0, screen_geometry.height() - current_geometry.height())
        target_x = min(max(global_pos.x() - current_geometry.width() // 2, screen_geometry.x()), max_x)
        target_y = min(max(global_pos.y() - current_geometry.height() // 2, screen_geometry.y()), max_y)
        target_geometry = QRect(
            target_x,
            target_y,
            current_geometry.width(),
            current_geometry.height(),
        )

        if target_geometry == current_geometry:
            self._focus_overlay()
            return True

        self._push_geometry_history(current_geometry)
        self.setGeometry(target_geometry)
        self.geometryChanged.emit(QRect(self.geometry()))
        self._focus_overlay()
        log_debug(
            "Overlay centered on cursor at "
            f"{global_pos.x()},{global_pos.y()} -> "
            f"{target_geometry.x()},{target_geometry.y()}"
        )
        return True

    def _get_resize_edge(self, pos: QPoint) -> ResizeEdge:
        """Determine which edge/corner the mouse is near."""
        m = self.RESIZE_MARGIN
        w = self.width()
        h = self.height()
        x = pos.x()
        y = pos.y()

        if x < m and y < m:
            return ResizeEdge.TOP_LEFT
        if x > w - m and y < m:
            return ResizeEdge.TOP_RIGHT
        if x < m and y > h - m:
            return ResizeEdge.BOTTOM_LEFT
        if x > w - m and y > h - m:
            return ResizeEdge.BOTTOM_RIGHT

        if x < m:
            return ResizeEdge.LEFT
        if x > w - m:
            return ResizeEdge.RIGHT
        if y < m:
            return ResizeEdge.TOP
        if y > h - m:
            return ResizeEdge.BOTTOM

        return ResizeEdge.NONE

    def _update_cursor(self, edge: ResizeEdge) -> None:
        cursors = {
            ResizeEdge.NONE: Qt.CursorShape.ArrowCursor,
            ResizeEdge.TOP: Qt.CursorShape.SizeVerCursor,
            ResizeEdge.BOTTOM: Qt.CursorShape.SizeVerCursor,
            ResizeEdge.LEFT: Qt.CursorShape.SizeHorCursor,
            ResizeEdge.RIGHT: Qt.CursorShape.SizeHorCursor,
            ResizeEdge.TOP_LEFT: Qt.CursorShape.SizeFDiagCursor,
            ResizeEdge.BOTTOM_RIGHT: Qt.CursorShape.SizeFDiagCursor,
            ResizeEdge.TOP_RIGHT: Qt.CursorShape.SizeBDiagCursor,
            ResizeEdge.BOTTOM_LEFT: Qt.CursorShape.SizeBDiagCursor,
        }
        self.setCursor(cursors.get(edge, Qt.CursorShape.ArrowCursor))

    def _do_resize(self, global_pos: QPoint) -> None:
        """Perform incremental resize based on current edge and mouse position."""
        x = self.x()
        y = self.y()
        w = self.width()
        h = self.height()

        dx = global_pos.x() - x
        dy = global_pos.y() - y

        if self._resize_edge in (ResizeEdge.RIGHT, ResizeEdge.TOP_RIGHT, ResizeEdge.BOTTOM_RIGHT):
            w = max(self.MIN_SIZE, dx)

        if self._resize_edge in (ResizeEdge.BOTTOM, ResizeEdge.BOTTOM_LEFT, ResizeEdge.BOTTOM_RIGHT):
            h = max(self.MIN_SIZE, dy)

        if self._resize_edge in (ResizeEdge.LEFT, ResizeEdge.TOP_LEFT, ResizeEdge.BOTTOM_LEFT):
            new_w = w - dx
            if new_w >= self.MIN_SIZE:
                w = new_w
                x += dx
            else:
                w = self.MIN_SIZE

        if self._resize_edge in (ResizeEdge.TOP, ResizeEdge.TOP_LEFT, ResizeEdge.TOP_RIGHT):
            new_h = h - dy
            if new_h >= self.MIN_SIZE:
                h = new_h
                y += dy
            else:
                h = self.MIN_SIZE

        self.setGeometry(x, y, w, h)

    def capture_region(self) -> None:
        """Capture the screen region covered by this overlay."""
        if not self._hotkey_enabled:
            log_debug("Hotkey is paused. Click toggle button to enable.")
            return

        if self._capture_in_progress:
            log_debug("Capture already in progress, ignoring duplicate trigger")
            return

        if not self.isVisible():
            log_debug("Overlay is hidden, ignoring capture request")
            return

        self._capture_in_progress = True

        geo = self.geometry()
        border = self.BORDER_WIDTH

        x1 = geo.x() + border
        y1 = geo.y() + border
        x2 = geo.x() + geo.width() - border
        y2 = geo.y() + geo.height() - border

        self._restore_after_capture = True
        self._pending_capture_rect = (x1, y1, x2, y2)
        self._suppress_hide_event = True
        self._suppress_show_event = True
        self.hide()
        # Force event processing so compositor applies hide before we grab screen.
        QApplication.processEvents()

        self._capture_timer.start(self._capture_hide_delay_ms)

    def set_capture_hide_delay_ms(self, delay_ms: int) -> None:
        """Set delay between hiding overlay and screen grab."""
        try:
            parsed = int(delay_ms)
        except (TypeError, ValueError):
            parsed = self.DEFAULT_CAPTURE_HIDE_DELAY_MS

        self._capture_hide_delay_ms = max(
            self.MIN_CAPTURE_HIDE_DELAY_MS,
            min(self.MAX_CAPTURE_HIDE_DELAY_MS, parsed)
        )

    def get_capture_hide_delay_ms(self) -> int:
        """Get current hide-to-capture delay in milliseconds."""
        return self._capture_hide_delay_ms

    def cancel_pending_capture_restore(self) -> None:
        """Cancel any delayed capture restore so the overlay stays hidden/closed."""
        had_pending_restore = self._suppress_show_event
        self._restore_after_capture = False
        self._pending_capture_rect = None
        if self._capture_timer.isActive():
            self._capture_timer.stop()
            self._capture_in_progress = False
        self._suppress_hide_event = False
        self._suppress_show_event = False
        if had_pending_restore and not self.isVisible():
            self.overlayVisibilityChanged.emit(False)

    def _run_pending_capture(self) -> None:
        """Run the delayed capture if one is still pending."""
        capture_rect = self._pending_capture_rect
        self._pending_capture_rect = None

        if capture_rect is None:
            self._capture_in_progress = False
            return
        if self._is_closing:
            self._capture_in_progress = False
            return

        self._do_capture(*capture_rect)

    def _do_capture(self, x1: int, y1: int, x2: int, y2: int) -> None:
        """Perform screen capture using DXcam with Qt fallback."""
        try:
            width = x2 - x1
            height = y2 - y1

            if width <= 0 or height <= 0:
                log_error(f"Invalid capture dimensions: {width}x{height}")
                return

            pil_image = None

            if DXCAM_AVAILABLE:
                try:
                    pil_image = self._capture_with_dxcam(x1, y1, width, height)
                except Exception as e:
                    if "Invalid Region" in str(e):
                        log_debug(f"DXcam region unavailable, falling back to Qt: {e}")
                    else:
                        log_warning(f"DXcam capture failed, falling back to Qt: {e}")
                    pil_image = None

            if pil_image is None:
                pil_image = self._capture_with_qt(x1, y1, width, height)

            if pil_image is not None:
                log_debug(f"Capture successful: {pil_image.size[0]}x{pil_image.size[1]}")
                self.captureCompleted.emit(pil_image)

        except Exception as e:
            log_error(f"Capture error: {e}")
        finally:
            self._capture_in_progress = False
            self._pending_capture_rect = None
            should_restore = self._restore_after_capture and not self._is_closing
            self._restore_after_capture = False
            if should_restore:
                self.show()
            else:
                self._suppress_show_event = False

    def _capture_with_dxcam(self, x: int, y: int, width: int, height: int) -> Image.Image:
        """Capture screen region using DXcam (Windows fast path)."""
        if self._dxcam_instance is None:
            raise RuntimeError("DXcam capture instance is not available")

        frame = self._dxcam_instance.grab(
            region=(x, y, x + width, y + height),
            new_frame_only=False,
        )
        if frame is None:
            raise RuntimeError("DXcam returned no frame")
        if len(frame.shape) != 3 or frame.shape[2] not in (3, 4):
            raise RuntimeError(f"Unexpected DXcam frame shape: {getattr(frame, 'shape', None)}")

        if frame.shape[2] == 4:
            rgba_frame = frame[:, :, [2, 1, 0, 3]].copy()
            return Image.fromarray(rgba_frame, "RGBA").convert("RGB")

        rgb_frame = frame[:, :, ::-1].copy()
        return Image.fromarray(rgb_frame, "RGB")

    def _capture_with_qt(self, x: int, y: int, width: int, height: int) -> Optional[Image.Image]:
        """Capture screen region using Qt's grabWindow (fallback path)."""
        center = QPoint(x + width // 2, y + height // 2)
        screen = QGuiApplication.screenAt(center)
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            log_error("No screen available for capture")
            return None

        screen_geo = screen.geometry()
        local_x = x - screen_geo.x()
        local_y = y - screen_geo.y()
        pixmap = screen.grabWindow(0, local_x, local_y, width, height)

        if pixmap.isNull():
            log_error("Screen capture returned null pixmap")
            return None

        qimage = pixmap.toImage()
        if qimage.isNull():
            log_error("Failed to convert pixmap to QImage")
            return None

        qimage = qimage.convertToFormat(qimage.Format.Format_RGB888)

        w = qimage.width()
        h = qimage.height()
        bytes_per_line = qimage.bytesPerLine()

        ptr = qimage.bits()
        ptr.setsize(h * bytes_per_line)

        return Image.frombytes("RGB", (w, h), bytes(ptr), "raw", "RGB", bytes_per_line)

    def get_capture_rect(self) -> Tuple[int, int, int, int]:
        geo = self.geometry()
        return (geo.x(), geo.y(), geo.width(), geo.height())

    def set_capture_rect(self, x: int, y: int, width: int, height: int) -> None:
        self.setGeometry(x, y, max(width, self.MIN_SIZE), max(height, self.MIN_SIZE))

    def save_geometry_string(self) -> str:
        """Save geometry as normalized ratios relative to the containing screen.

        Format: 'rw,rh,rx,ry' where values are floats relative to screen size.
        The presence of ',' and '.' distinguishes this from the legacy 'WxH+X+Y' format.
        """
        geo = self.geometry()
        center = geo.center()

        screen = QGuiApplication.screenAt(center)
        if screen is None:
            screen = QGuiApplication.primaryScreen()

        if screen is None:
            return f"{geo.width()}x{geo.height()}+{geo.x()}+{geo.y()}"

        sg = screen.geometry()

        rx = (geo.x() - sg.x()) / sg.width() if sg.width() > 0 else 0.0
        ry = (geo.y() - sg.y()) / sg.height() if sg.height() > 0 else 0.0
        rw = geo.width() / sg.width() if sg.width() > 0 else 0.5
        rh = geo.height() / sg.height() if sg.height() > 0 else 0.5

        rx = max(-0.5, min(1.5, rx))
        ry = max(-0.5, min(1.5, ry))
        rw = max(0.01, min(1.0, rw))
        rh = max(0.01, min(1.0, rh))

        return f"{rw:.6f},{rh:.6f},{rx:.6f},{ry:.6f}"

    def restore_geometry_string(self, geometry_str: str) -> bool:
        """Restore geometry from either normalized ratio or legacy absolute format.

        Normalized format: 'rw,rh,rx,ry' (contains ',' and '.')
        Legacy format: 'WxH+X+Y' (integers only)
        """
        try:
            if ',' in geometry_str and '.' in geometry_str:
                return self._restore_normalized_geometry(geometry_str)
            else:
                return self._restore_legacy_geometry(geometry_str)
        except (ValueError, IndexError) as e:
            log_debug(f"Failed to restore geometry '{geometry_str}': {e}")
            return False

    def _restore_normalized_geometry(self, geometry_str: str) -> bool:
        """Restore from normalized ratio format: 'rw,rh,rx,ry'."""
        parts = geometry_str.split(',')
        if len(parts) < 4:
            return False

        rw, rh, rx, ry = float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])

        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return False

        sg = screen.geometry()

        x = int(sg.x() + rx * sg.width())
        y = int(sg.y() + ry * sg.height())
        w = max(self.MIN_SIZE, int(rw * sg.width()))
        h = max(self.MIN_SIZE, int(rh * sg.height()))

        if self._is_position_valid(x, y, w, h):
            self.setGeometry(x, y, w, h)
            return True

        for s in QGuiApplication.screens():
            sg2 = s.geometry()
            x2 = int(sg2.x() + rx * sg2.width())
            y2 = int(sg2.y() + ry * sg2.height())
            w2 = max(self.MIN_SIZE, int(rw * sg2.width()))
            h2 = max(self.MIN_SIZE, int(rh * sg2.height()))
            if self._is_position_valid(x2, y2, w2, h2):
                self.setGeometry(x2, y2, w2, h2)
                return True

        return False

    def _restore_legacy_geometry(self, geometry_str: str) -> bool:
        """Restore from legacy absolute format: 'WxH+X+Y'."""
        parts = geometry_str.replace('x', '+').split('+')
        if len(parts) < 4:
            return False

        w, h, x, y = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
        if self._is_position_valid(x, y, w, h):
            self.setGeometry(x, y, max(w, self.MIN_SIZE), max(h, self.MIN_SIZE))
            return True
        return False

    def _is_position_valid(self, x: int, y: int, w: int, h: int) -> bool:
        """Check if position is visible on any screen."""
        rect = QRect(x, y, w, h)
        for screen in QGuiApplication.screens():
            if screen.geometry().intersects(rect):
                return True
        return False

    def closeEvent(self, event) -> None:
        self._is_closing = True
        self.cancel_pending_capture_restore()
        if self._dxcam_instance is not None:
            try:
                self._dxcam_instance.release()
            except Exception:
                pass
            self._dxcam_instance = None
        super().closeEvent(event)
