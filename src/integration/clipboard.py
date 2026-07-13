"""
Clipboard Manager - Cross-platform clipboard operations.

Uses Qt's QClipboard for better integration and MIME type support,
with pyperclip as fallback.
"""

from __future__ import annotations
from typing import Optional
from PIL import Image

from ..utils.logger import log_error, log_debug


class ClipboardManager:
    """Manages clipboard operations with Qt and pyperclip support."""

    def __init__(self, use_qt: bool = True) -> None:
        self._use_qt = use_qt
        self._qt_clipboard = None

    def _get_qt_clipboard(self):
        if not self._use_qt:
            return None

        if self._qt_clipboard is not None:
            return self._qt_clipboard

        try:
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                self._qt_clipboard = app.clipboard()
                return self._qt_clipboard
        except ImportError:
            pass
        return None

    def copy_text(self, text: str) -> bool:
        """Copy text to clipboard."""
        qt_clip = self._get_qt_clipboard()
        if qt_clip is not None:
            try:
                qt_clip.setText(text)
                return True
            except Exception as e:
                log_error(f"Qt clipboard error: {e}")

        try:
            import pyperclip
            pyperclip.copy(text)
            return True
        except Exception as e:
            log_error(f"pyperclip error: {e}")
            return False

    @staticmethod
    def _pil_to_qimage(image: Image.Image):
        """Convert PIL image to QImage with minimal conversions."""
        from PyQt6.QtGui import QImage

        if image.mode == "RGB":
            data = image.tobytes("raw", "RGB")
            qimage = QImage(
                data,
                image.width,
                image.height,
                image.width * 3,
                QImage.Format.Format_RGB888,
            )
            return qimage, data

        if image.mode != "RGBA":
            image = image.convert("RGBA")

        data = image.tobytes("raw", "RGBA")
        qimage = QImage(
            data,
            image.width,
            image.height,
            image.width * 4,
            QImage.Format.Format_RGBA8888,
        )
        return qimage, data

    def copy_image(self, image: Image.Image) -> bool:
        """Copy image to clipboard."""
        qt_clip = self._get_qt_clipboard()
        if qt_clip is not None:
            try:
                from PyQt6.QtGui import QPixmap

                qimage, _buffer = self._pil_to_qimage(image)
                qt_clip.setPixmap(QPixmap.fromImage(qimage))
                return True
            except Exception as e:
                log_error(f"Qt image clipboard error: {e}")
        return False

    def copy_text_and_image(self, text: str, image: Image.Image) -> bool:
        """Copy both text and image to clipboard using MIME types."""
        qt_clip = self._get_qt_clipboard()
        if qt_clip is not None:
            try:
                from PyQt6.QtCore import QMimeData

                mime_data = QMimeData()
                mime_data.setText(text)

                qimage, _buffer = self._pil_to_qimage(image)
                mime_data.setImageData(qimage.copy())

                qt_clip.setMimeData(mime_data)
                return True
            except Exception as e:
                log_error(f"Qt MIME clipboard error: {e}")

        return self.copy_text(text)

    def get_text(self) -> Optional[str]:
        """Get text from clipboard."""
        qt_clip = self._get_qt_clipboard()
        if qt_clip is not None:
            try:
                text = qt_clip.text()
                return text if text else None
            except Exception:
                pass

        try:
            import pyperclip
            text = pyperclip.paste()
            return text if text else None
        except Exception:
            return None

    def get_image(self) -> Optional[Image.Image]:
        """Get image from clipboard."""
        qt_clip = self._get_qt_clipboard()
        if qt_clip is not None:
            try:
                from PyQt6.QtGui import QImage

                qimage = qt_clip.image()
                if qimage.isNull():
                    return None

                if qimage.format() != QImage.Format.Format_RGBA8888:
                    qimage = qimage.convertToFormat(QImage.Format.Format_RGBA8888)
                width = qimage.width()
                height = qimage.height()

                ptr = qimage.bits()
                ptr.setsize(qimage.sizeInBytes())

                return Image.frombytes(
                    'RGBA', (width, height),
                    bytes(ptr), 'raw', 'RGBA'
                )
            except Exception as e:
                log_error(f"Qt image read error: {e}")
        return None


_clipboard_manager: Optional[ClipboardManager] = None


def get_clipboard() -> ClipboardManager:
    """Get the global clipboard manager instance."""
    global _clipboard_manager
    if _clipboard_manager is None:
        _clipboard_manager = ClipboardManager()
    return _clipboard_manager


def copy_text(text: str) -> bool:
    return get_clipboard().copy_text(text)


def copy_image(image: Image.Image) -> bool:
    return get_clipboard().copy_image(image)


def get_text() -> Optional[str]:
    return get_clipboard().get_text()
