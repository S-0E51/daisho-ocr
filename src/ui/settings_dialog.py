"""
Settings Dialog - Configuration UI with tabs for the OCR tool.
"""

from __future__ import annotations
import os
from typing import Callable, Optional
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QPushButton, QLineEdit, QComboBox, QSpinBox,
    QCheckBox, QTabWidget, QWidget, QFormLayout, QDoubleSpinBox,
    QMessageBox, QFileDialog
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeySequence

from ..utils.logger import log_info, log_error, log_debug
from ..processing.image_ops import PreprocessingMode, get_available_modes, mode_description
from ..ocr.comparison import (
    OCR_COMPARISON_ENGINE_LABELS,
    OCR_COMPARISON_MODE_LABELS,
    normalize_comparison_engine,
    normalize_comparison_mode,
)
from ..ocr.manager import OCREngine, get_engine_name, get_engine_description
from ..ocr.paddle_engine import (
    DEFAULT_PADDLE_PROFILE,
    get_available_paddle_profiles,
    get_paddle_profile_name,
    get_paddle_profile_description,
)
from ..ocr.vision_verifier import (
    DEFAULT_GEMMA_VISION_MODEL,
    DEFAULT_OLLAMA_VISION_MODEL,
    DEFAULT_VISION_VERIFICATION_CONFIDENCE,
    OLLAMA_MODEL_PREFIX,
    VISION_VERIFICATION_MODE_LABELS,
    normalize_verification_mode,
    normalize_verification_model,
)
from ..ocr.cache import get_ocr_cache
from ..integration.japreader import (
    detect_japreader,
    detect_managed_japreader,
    launch_japreader,
)
from ..integration.japreader_manager import (
    INTEGRATION_DIRECT,
    INTEGRATION_DISABLED,
    INTEGRATION_LEGACY,
    POST_CAPTURE_FOCUS,
    POST_CAPTURE_HIDDEN,
    POST_CAPTURE_REVEAL,
    normalize_post_capture_behavior,
)
from .theme import (
    SETTINGS_DIALOG_STYLE,
    HOTKEY_EDIT_RECORDING_STYLE,
    HOTKEY_EDIT_IDLE_STYLE,
    SETTINGS_MUTED_LABEL_STYLE,
    SETTINGS_SUCCESS_LABEL_STYLE,
    SETTINGS_WARNING_LABEL_STYLE,
    SETTINGS_TITLE_STYLE,
    SETTINGS_SUBTITLE_STYLE,
)


# =============================================================================
# Custom Hotkey Recording Widget
# =============================================================================

class HotkeyEdit(QLineEdit):
    """Custom line edit for recording keyboard shortcuts and mouse buttons."""

    hotkeyChanged = pyqtSignal(str)

    MOUSE_BUTTON_NAMES = {
        Qt.MouseButton.MiddleButton: "middle",
        Qt.MouseButton.BackButton: "mouse4",
        Qt.MouseButton.ForwardButton: "mouse5",
    }

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._recording = False
        self._modifiers: set[str] = set()
        self._key = ""
        self._is_mouse_button = False
        self.setReadOnly(True)
        self.setPlaceholderText("Click to record hotkey...")
        self.setStyleSheet(HOTKEY_EDIT_IDLE_STYLE)

    def mousePressEvent(self, event) -> None:
        if not self._recording:
            self._start_recording()
        else:
            button = event.button()
            if button in self.MOUSE_BUTTON_NAMES:
                self._key = self.MOUSE_BUTTON_NAMES[button]
                self._is_mouse_button = True
                self._update_display()
                self._stop_recording()
                return
        super().mousePressEvent(event)

    def _start_recording(self) -> None:
        self._recording = True
        self._modifiers.clear()
        self._key = ""
        self._is_mouse_button = False
        self.setText("Press key or mouse button...")
        self.setStyleSheet(HOTKEY_EDIT_RECORDING_STYLE)

    def keyPressEvent(self, event) -> None:
        if not self._recording:
            return

        modifiers = event.modifiers()
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            self._modifiers.add("ctrl")
        if modifiers & Qt.KeyboardModifier.AltModifier:
            self._modifiers.add("alt")
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            self._modifiers.add("shift")
        if modifiers & Qt.KeyboardModifier.MetaModifier:
            self._modifiers.add("win")

        key_name = self._key_to_string(event.key())
        if key_name:
            self._key = key_name

        self._update_display()

    def keyReleaseEvent(self, event) -> None:
        if self._recording and self._key:
            self._stop_recording()

    def _stop_recording(self) -> None:
        self._recording = False
        self.setStyleSheet(HOTKEY_EDIT_IDLE_STYLE)

        if self._modifiers or self._key:
            hotkey = self._build_hotkey_string()
            self.setText(hotkey)
            self.hotkeyChanged.emit(hotkey)

    def _update_display(self) -> None:
        self.setText(self._build_hotkey_string())

    def _build_hotkey_string(self) -> str:
        parts = []
        for mod in ["ctrl", "alt", "shift", "win"]:
            if mod in self._modifiers:
                parts.append(mod)
        if self._key:
            parts.append(self._key)
        return "+".join(parts) if parts else ""

    def _key_to_string(self, key: int) -> str:
        modifier_keys = {
            Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Shift,
            Qt.Key.Key_Meta, Qt.Key.Key_AltGr
        }
        if key in modifier_keys:
            return ""

        special_keys = {
            Qt.Key.Key_Space: "space",
            Qt.Key.Key_Return: "enter",
            Qt.Key.Key_Enter: "enter",
            Qt.Key.Key_Tab: "tab",
            Qt.Key.Key_Escape: "esc",
            Qt.Key.Key_Backspace: "backspace",
            Qt.Key.Key_Delete: "delete",
            Qt.Key.Key_Up: "up",
            Qt.Key.Key_Down: "down",
            Qt.Key.Key_Left: "left",
            Qt.Key.Key_Right: "right",
            Qt.Key.Key_Home: "home",
            Qt.Key.Key_End: "end",
            Qt.Key.Key_PageUp: "pageup",
            Qt.Key.Key_PageDown: "pagedown",
            Qt.Key.Key_Insert: "insert",
        }

        if key in special_keys:
            return special_keys[key]

        if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F12:
            return f"f{key - Qt.Key.Key_F1 + 1}"

        seq = QKeySequence(key)
        text = seq.toString().lower()
        return text if len(text) == 1 else ""

    def set_hotkey(self, hotkey: Optional[str]) -> None:
        hotkey_text = hotkey if isinstance(hotkey, str) else ""
        self.setText(hotkey_text)
        parts = hotkey_text.lower().split("+") if hotkey_text else []
        self._modifiers = {p for p in parts if p in ("ctrl", "alt", "shift", "win")}
        self._key = next((p for p in parts if p not in self._modifiers), "")
        self._is_mouse_button = any(
            mb in hotkey_text.lower() for mb in ["mouse4", "mouse5", "middle"]
        )

    def get_hotkey(self) -> str:
        text = self.text()
        if text in ("", "Press key or mouse button...", "Click to record hotkey..."):
            return ""
        return text


# =============================================================================
# Settings Dialog
# =============================================================================

class SettingsDialog(QDialog):
    """Settings dialog with tabs for General, Processing, Integrations, and About."""

    settingsChanged = pyqtSignal(dict)
    MIN_CAPTURE_HIDE_DELAY_MS = 30
    MAX_CAPTURE_HIDE_DELAY_MS = 500
    DEFAULT_CAPTURE_HIDE_DELAY_MS = 120

    def __init__(
        self,
        current_settings: dict,
        parent: Optional[QWidget] = None,
        *,
        japreader_status_provider: Optional[Callable[[], object]] = None,
    ) -> None:
        super().__init__(parent)
        self._settings = current_settings.copy()
        self._detected_japreader_path = ""
        self._japreader_status_provider = japreader_status_provider
        self._setup_ui()
        self._load_settings()

    def _setup_ui(self) -> None:
        self.setWindowTitle("Settings")
        self.setMinimumSize(520, 480)
        self.setStyleSheet(SETTINGS_DIALOG_STYLE)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        tabs = QTabWidget()
        tabs.addTab(self._create_general_tab(), "General")
        tabs.addTab(self._create_processing_tab(), "Processing")
        tabs.addTab(self._create_integrations_tab(), "Integrations")
        tabs.addTab(self._create_about_tab(), "About")
        layout.addWidget(tabs)

        button_layout = QHBoxLayout()
        button_layout.addStretch()

        apply_btn = QPushButton("Apply")
        apply_btn.setObjectName("secondary")
        apply_btn.clicked.connect(self._apply_settings)
        button_layout.addWidget(apply_btn)

        ok_btn = QPushButton("OK")
        ok_btn.setObjectName("primary")
        ok_btn.clicked.connect(self._ok_clicked)
        button_layout.addWidget(ok_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

    # =========================================================================
    # Tab: General
    # =========================================================================

    def _create_general_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)

        # --- Capture ---
        capture_group = QGroupBox("Capture")
        capture_layout = QFormLayout(capture_group)
        capture_layout.setSpacing(8)

        self._hotkey_edit = HotkeyEdit()
        capture_layout.addRow("Hotkey:", self._hotkey_edit)

        self._overlay_to_mouse_hotkey_edit = HotkeyEdit()
        capture_layout.addRow("Move overlay to mouse:", self._overlay_to_mouse_hotkey_edit)

        self._allow_move_overlay_when_hidden_cb = QCheckBox(
            "Allow move overlay hotkey while overlay is hidden"
        )
        capture_layout.addRow(self._allow_move_overlay_when_hidden_cb)

        self._allow_move_overlay_when_locked_cb = QCheckBox(
            "Allow move overlay hotkey while capture is locked"
        )
        capture_layout.addRow(self._allow_move_overlay_when_locked_cb)

        hint = QLabel(
            "Click to record. Supports keyboard combos, mouse4/5, middle click."
        )
        hint.setStyleSheet(SETTINGS_MUTED_LABEL_STYLE)
        hint.setWordWrap(True)
        capture_layout.addRow(hint)

        move_hint = QLabel(
            "Shows the overlay and centers it on the cursor using the current overlay size."
        )
        move_hint.setStyleSheet(SETTINGS_MUTED_LABEL_STYLE)
        move_hint.setWordWrap(True)
        capture_layout.addRow(move_hint)

        hidden_move_hint = QLabel(
            "Disabled by default. Turn this on if you want the move hotkey to reopen the overlay when it is hidden."
        )
        hidden_move_hint.setStyleSheet(SETTINGS_MUTED_LABEL_STYLE)
        hidden_move_hint.setWordWrap(True)
        capture_layout.addRow(hidden_move_hint)

        locked_move_hint = QLabel(
            "Disabled by default. Turn this on if you want the move hotkey to keep working when capture is locked and the overlay toggle is yellow."
        )
        locked_move_hint.setStyleSheet(SETTINGS_MUTED_LABEL_STYLE)
        locked_move_hint.setWordWrap(True)
        capture_layout.addRow(locked_move_hint)

        self._capture_hide_delay_spin = QSpinBox()
        self._capture_hide_delay_spin.setRange(
            self.MIN_CAPTURE_HIDE_DELAY_MS,
            self.MAX_CAPTURE_HIDE_DELAY_MS,
        )
        self._capture_hide_delay_spin.setSingleStep(10)
        self._capture_hide_delay_spin.setSuffix(" ms")
        capture_layout.addRow("Overlay hide delay:", self._capture_hide_delay_spin)

        delay_hint = QLabel("Increase this if first capture misses after clicking on the overlay.")
        delay_hint.setStyleSheet(SETTINGS_MUTED_LABEL_STYLE)
        delay_hint.setWordWrap(True)
        capture_layout.addRow(delay_hint)

        layout.addWidget(capture_group)

        # --- OCR Engine ---
        engine_group = QGroupBox("OCR Engine")
        engine_layout = QFormLayout(engine_group)
        engine_layout.setSpacing(8)

        self._engine_combo = QComboBox()
        for engine in OCREngine:
            self._engine_combo.addItem(get_engine_name(engine), engine.value)
        self._engine_combo.currentIndexChanged.connect(self._on_engine_change)
        engine_layout.addRow("Engine:", self._engine_combo)

        self._engine_desc_label = QLabel("")
        self._engine_desc_label.setStyleSheet(SETTINGS_MUTED_LABEL_STYLE)
        self._engine_desc_label.setWordWrap(True)
        engine_layout.addRow(self._engine_desc_label)

        self._paddle_profile_combo = QComboBox()
        for profile in get_available_paddle_profiles():
            self._paddle_profile_combo.addItem(get_paddle_profile_name(profile), profile)
        self._paddle_profile_combo.currentIndexChanged.connect(self._update_paddle_profile_ui)
        engine_layout.addRow("Paddle mode:", self._paddle_profile_combo)

        self._paddle_profile_desc_label = QLabel("")
        self._paddle_profile_desc_label.setStyleSheet(SETTINGS_MUTED_LABEL_STYLE)
        self._paddle_profile_desc_label.setWordWrap(True)
        engine_layout.addRow(self._paddle_profile_desc_label)

        self._keep_inactive_engines_warm_cb = QCheckBox("Keep inactive OCR engines warm in memory")
        engine_layout.addRow(self._keep_inactive_engines_warm_cb)

        warm_hint = QLabel(
            "Recommended off. When disabled, only the active engine stays loaded and the others "
            "lazy-load on demand. When enabled, inactive engines stay warm for faster switching "
            "at the cost of more RAM and VRAM."
        )
        warm_hint.setStyleSheet(SETTINGS_MUTED_LABEL_STYLE)
        warm_hint.setWordWrap(True)
        engine_layout.addRow(warm_hint)

        layout.addWidget(engine_group)

        # --- Behavior ---
        behavior_group = QGroupBox("Behavior")
        behavior_layout = QVBoxLayout(behavior_group)
        behavior_layout.setSpacing(6)

        self._auto_copy_cb = QCheckBox("Auto-copy OCR result to clipboard")
        behavior_layout.addWidget(self._auto_copy_cb)

        self._show_notification_cb = QCheckBox("Show notification after capture")
        behavior_layout.addWidget(self._show_notification_cb)

        self._start_minimized_cb = QCheckBox("Start minimized to system tray")
        behavior_layout.addWidget(self._start_minimized_cb)

        layout.addWidget(behavior_group)

        layout.addStretch()
        return widget

    # =========================================================================
    # Tab: Processing
    # =========================================================================

    def _create_processing_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)

        # --- Image Preprocessing ---
        preprocess_group = QGroupBox("Image Preprocessing")
        preprocess_layout = QVBoxLayout(preprocess_group)
        preprocess_layout.setSpacing(8)

        mode_row = QFormLayout()
        mode_row.setSpacing(8)
        self._preprocess_combo = QComboBox()
        for mode in get_available_modes():
            self._preprocess_combo.addItem(mode_description(mode), mode.value)
        mode_row.addRow("Mode:", self._preprocess_combo)
        preprocess_layout.addLayout(mode_row)

        self._auto_crop_cb = QCheckBox("Auto-crop to detected text region")
        preprocess_layout.addWidget(self._auto_crop_cb)

        self._detect_orientation_cb = QCheckBox("Detect text orientation")
        preprocess_layout.addWidget(self._detect_orientation_cb)

        self._post_correction_cb = QCheckBox("Conservative post-OCR correction")
        preprocess_layout.addWidget(self._post_correction_cb)

        correction_hint = QLabel(
            "Uses Japanese morphology to fix high-confidence small-kana OCR mistakes like "
            "ずつと -> ずっと without attempting freeform rewrites."
        )
        correction_hint.setWordWrap(True)
        correction_hint.setStyleSheet(SETTINGS_MUTED_LABEL_STYLE)
        preprocess_layout.addWidget(correction_hint)

        comparison_row = QFormLayout()
        comparison_row.setSpacing(8)

        self._comparison_mode_combo = QComboBox()
        for mode, label in OCR_COMPARISON_MODE_LABELS.items():
            self._comparison_mode_combo.addItem(label, mode)
        self._comparison_mode_combo.currentIndexChanged.connect(self._update_comparison_controls)
        comparison_row.addRow("OCR comparison:", self._comparison_mode_combo)

        self._comparison_engine_combo = QComboBox()
        for engine_value, label in OCR_COMPARISON_ENGINE_LABELS.items():
            self._comparison_engine_combo.addItem(label, engine_value)
        comparison_row.addRow("Secondary engine:", self._comparison_engine_combo)
        preprocess_layout.addLayout(comparison_row)

        self._comparison_hint_label = QLabel(
            "Runs a secondary OCR pass and compares the outputs. Suspicious Only is "
            "recommended so the second engine only runs when the first read looks risky."
        )
        self._comparison_hint_label.setWordWrap(True)
        self._comparison_hint_label.setStyleSheet(SETTINGS_MUTED_LABEL_STYLE)
        preprocess_layout.addWidget(self._comparison_hint_label)

        verification_row = QFormLayout()
        verification_row.setSpacing(8)

        self._verification_mode_combo = QComboBox()
        for mode, label in VISION_VERIFICATION_MODE_LABELS.items():
            self._verification_mode_combo.addItem(label, mode)
        self._verification_mode_combo.currentIndexChanged.connect(
            self._update_verification_controls
        )
        verification_row.addRow("Vision verification:", self._verification_mode_combo)

        self._verification_model_edit = QLineEdit()
        self._verification_model_edit.setPlaceholderText(
            f"{OLLAMA_MODEL_PREFIX}{DEFAULT_OLLAMA_VISION_MODEL}"
        )
        verification_row.addRow("Gemma model:", self._verification_model_edit)

        self._verification_confidence_spin = QDoubleSpinBox()
        self._verification_confidence_spin.setRange(0.50, 0.99)
        self._verification_confidence_spin.setDecimals(2)
        self._verification_confidence_spin.setSingleStep(0.01)
        verification_row.addRow("Accept correction at:", self._verification_confidence_spin)
        preprocess_layout.addLayout(verification_row)

        self._verification_hint_label = QLabel(
            "Uses a vision model to compare the image against the selected OCR text. "
            f"Use {OLLAMA_MODEL_PREFIX}{DEFAULT_OLLAMA_VISION_MODEL} for the local Ollama model. "
            "Always Verify catches same-result OCR hallucinations, but it is slower."
        )
        self._verification_hint_label.setWordWrap(True)
        self._verification_hint_label.setStyleSheet(SETTINGS_MUTED_LABEL_STYLE)
        preprocess_layout.addWidget(self._verification_hint_label)

        layout.addWidget(preprocess_group)

        # --- Cache ---
        cache_group = QGroupBox("Cache")
        cache_layout = QVBoxLayout(cache_group)
        cache_layout.setSpacing(8)

        self._cache_enabled_cb = QCheckBox("Enable result caching")
        cache_layout.addWidget(self._cache_enabled_cb)

        cache_size_row = QFormLayout()
        cache_size_row.setSpacing(8)
        self._cache_size_spin = QSpinBox()
        self._cache_size_spin.setRange(16, 4096)
        self._cache_size_spin.setSingleStep(64)
        self._cache_size_spin.setSuffix(" MB")
        cache_size_row.addRow("Maximum size:", self._cache_size_spin)
        cache_layout.addLayout(cache_size_row)

        self._cache_stats_label = QLabel("Cache: Not initialized")
        self._cache_stats_label.setStyleSheet(SETTINGS_MUTED_LABEL_STYLE)
        cache_layout.addWidget(self._cache_stats_label)

        clear_cache_btn = QPushButton("Clear Cache")
        clear_cache_btn.setFixedWidth(120)
        clear_cache_btn.clicked.connect(self._clear_cache)
        cache_layout.addWidget(clear_cache_btn)

        layout.addWidget(cache_group)

        layout.addStretch()
        return widget

    # =========================================================================
    # Tab: Integrations
    # =========================================================================

    def _create_integrations_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)

        japreader_group = QGroupBox("japReader Integration")
        japreader_layout = QVBoxLayout(japreader_group)
        japreader_layout.setSpacing(8)

        japreader_help = QLabel("Auto-launch japReader alongside 代書 for dictionary lookups.")
        japreader_help.setWordWrap(True)
        japreader_help.setStyleSheet(SETTINGS_MUTED_LABEL_STYLE)
        japreader_layout.addWidget(japreader_help)

        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(6)
        mode_layout.addWidget(QLabel("Mode:"))
        self._japreader_mode_combo = QComboBox()
        self._japreader_mode_combo.addItem("Direct local bridge", INTEGRATION_DIRECT)
        self._japreader_mode_combo.addItem("Legacy clipboard", INTEGRATION_LEGACY)
        self._japreader_mode_combo.addItem("Disabled", INTEGRATION_DISABLED)
        mode_layout.addWidget(self._japreader_mode_combo, 1)
        japreader_layout.addLayout(mode_layout)

        self._japreader_send_cb = QCheckBox("Send OCR results to japReader")
        japreader_layout.addWidget(self._japreader_send_cb)

        self._japreader_autolaunch_cb = QCheckBox("Auto-launch japReader on startup")
        japreader_layout.addWidget(self._japreader_autolaunch_cb)

        behavior_layout = QHBoxLayout()
        behavior_layout.setSpacing(6)
        behavior_layout.addWidget(QLabel("After capture:"))
        self._japreader_behavior_combo = QComboBox()
        self._japreader_behavior_combo.addItem(
            "Reveal without focusing (direct mode)",
            POST_CAPTURE_REVEAL,
        )
        self._japreader_behavior_combo.addItem(
            "Bring japReader to front",
            POST_CAPTURE_FOCUS,
        )
        self._japreader_behavior_combo.addItem(
            "Keep japReader hidden",
            POST_CAPTURE_HIDDEN,
        )
        behavior_layout.addWidget(self._japreader_behavior_combo, 1)
        japreader_layout.addLayout(behavior_layout)

        self._japreader_fallback_cb = QCheckBox(
            "Use clipboard fallback when direct delivery is unavailable"
        )
        japreader_layout.addWidget(self._japreader_fallback_cb)

        path_layout = QHBoxLayout()
        path_layout.setSpacing(6)
        path_label = QLabel("Path:")
        self._japreader_path_edit = QLineEdit()
        self._japreader_path_edit.setPlaceholderText("Auto-detect or browse...")
        self._japreader_path_edit.textChanged.connect(self._on_japreader_path_changed)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_japreader_path)

        path_layout.addWidget(path_label)
        path_layout.addWidget(self._japreader_path_edit, 1)
        path_layout.addWidget(browse_btn)
        japreader_layout.addLayout(path_layout)

        status_layout = QHBoxLayout()
        status_layout.setSpacing(6)
        self._japreader_status_label = QLabel("")
        self._japreader_status_label.setStyleSheet(SETTINGS_MUTED_LABEL_STYLE)
        status_layout.addWidget(self._japreader_status_label, 1)

        launch_btn = QPushButton("Launch japReader")
        launch_btn.clicked.connect(self._launch_japreader)
        self._japreader_launch_btn = launch_btn
        self._japreader_launch_btn.setEnabled(False)
        status_layout.addWidget(launch_btn)
        japreader_layout.addLayout(status_layout)

        runtime_layout = QHBoxLayout()
        runtime_layout.setSpacing(6)
        self._japreader_runtime_status_label = QLabel("")
        self._japreader_runtime_status_label.setWordWrap(True)
        self._japreader_runtime_status_label.setStyleSheet(SETTINGS_MUTED_LABEL_STYLE)
        runtime_layout.addWidget(self._japreader_runtime_status_label, 1)
        refresh_btn = QPushButton("Refresh status")
        refresh_btn.clicked.connect(self._refresh_japreader_runtime_status)
        runtime_layout.addWidget(refresh_btn)
        japreader_layout.addLayout(runtime_layout)
        self._japreader_mode_combo.currentIndexChanged.connect(
            self._on_japreader_mode_changed
        )

        layout.addWidget(japreader_group)
        self._detect_japreader_ui()
        self._refresh_japreader_runtime_status()

        layout.addStretch()
        return widget

    # =========================================================================
    # Tab: About
    # =========================================================================

    def _create_about_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        title = QLabel("代書")
        title.setStyleSheet(SETTINGS_TITLE_STYLE)
        layout.addWidget(title)

        subtitle = QLabel("Daisho - Japanese OCR")
        subtitle.setStyleSheet(SETTINGS_SUBTITLE_STYLE)
        layout.addWidget(subtitle)

        version = QLabel("Version 3.0.0")
        layout.addWidget(version)

        description = QLabel(
            "A high-precision Japanese OCR desktop application.\n\n"
            "Features:\n"
            "- Multiple OCR engines (PP-OCRv5, manga-ocr, Surya OCR)\n"
            "- Transparent overlay for easy region selection\n"
            "- Advanced image preprocessing options\n"
            "- Global hotkey and mouse button support\n"
            "- OCR result caching\n"
            "- japReader integration\n"
            "- GPU acceleration support"
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        links = QLabel(
            '<a href="https://github.com/PaddlePaddle/PaddleOCR">PaddleOCR</a> · '
            '<a href="https://github.com/kha-white/manga-ocr">manga-ocr</a> · '
            '<a href="https://github.com/datalab-to/surya">Surya OCR</a>'
        )
        links.setOpenExternalLinks(True)
        layout.addWidget(links)

        layout.addStretch()
        return widget

    # =========================================================================
    # Settings Load / Apply
    # =========================================================================

    def _load_settings(self) -> None:
        """Load current settings into UI controls."""
        self._hotkey_edit.set_hotkey(self._settings.get("capture_hotkey", "ctrl+shift"))
        self._overlay_to_mouse_hotkey_edit.set_hotkey(
            self._settings.get("overlay_to_mouse_hotkey", "`")
        )
        self._allow_move_overlay_when_hidden_cb.setChecked(
            self._normalize_bool_setting(
                self._settings.get("allow_move_overlay_to_mouse_when_hidden", False),
                default=False,
            )
        )
        self._allow_move_overlay_when_locked_cb.setChecked(
            self._normalize_bool_setting(
                self._settings.get("allow_move_overlay_to_mouse_when_locked", False),
                default=False,
            )
        )
        self._capture_hide_delay_spin.setValue(
            self._normalize_capture_hide_delay_ms(
                self._settings.get("capture_hide_delay_ms", self.DEFAULT_CAPTURE_HIDE_DELAY_MS)
            )
        )

        engine = self._settings.get("ocr_engine", OCREngine.PADDLE_OCR.value)
        engine_index = self._engine_combo.findData(engine)
        if engine_index >= 0:
            self._engine_combo.setCurrentIndex(engine_index)
        self._update_engine_description()

        paddle_profile = self._settings.get("paddle_profile", DEFAULT_PADDLE_PROFILE)
        profile_index = self._paddle_profile_combo.findData(paddle_profile)
        if profile_index < 0:
            profile_index = self._paddle_profile_combo.findData(DEFAULT_PADDLE_PROFILE)
        if profile_index >= 0:
            self._paddle_profile_combo.setCurrentIndex(profile_index)
        self._update_paddle_profile_ui()

        mode = self._settings.get("preprocessing_mode", "none")
        index = self._preprocess_combo.findData(mode)
        if index >= 0:
            self._preprocess_combo.setCurrentIndex(index)

        self._auto_crop_cb.setChecked(
            self._normalize_bool_setting(self._settings.get("auto_crop", True), default=True)
        )
        self._detect_orientation_cb.setChecked(
            self._normalize_bool_setting(
                self._settings.get("detect_orientation", True),
                default=True,
            )
        )
        self._post_correction_cb.setChecked(
            self._normalize_bool_setting(
                self._settings.get("post_correction_enabled", True),
                default=True,
            )
        )
        self._keep_inactive_engines_warm_cb.setChecked(
            self._normalize_bool_setting(
                self._settings.get("keep_inactive_ocr_engines_warm", False),
                default=False,
            )
        )
        comparison_mode = normalize_comparison_mode(
            self._settings.get("ocr_comparison_mode", "off")
        )
        comparison_mode_index = self._comparison_mode_combo.findData(comparison_mode)
        if comparison_mode_index >= 0:
            self._comparison_mode_combo.setCurrentIndex(comparison_mode_index)
        comparison_engine = normalize_comparison_engine(
            self._settings.get("ocr_comparison_engine", "auto")
        )
        comparison_engine_index = self._comparison_engine_combo.findData(comparison_engine)
        if comparison_engine_index >= 0:
            self._comparison_engine_combo.setCurrentIndex(comparison_engine_index)
        self._update_comparison_controls()

        verification_mode = normalize_verification_mode(
            self._settings.get("ocr_verification_mode", "off")
        )
        verification_mode_index = self._verification_mode_combo.findData(verification_mode)
        if verification_mode_index >= 0:
            self._verification_mode_combo.setCurrentIndex(verification_mode_index)
        self._verification_model_edit.setText(
            normalize_verification_model(
                self._settings.get("ocr_verification_model", DEFAULT_GEMMA_VISION_MODEL)
            )
        )
        self._verification_confidence_spin.setValue(
            self._normalize_float_setting(
                self._settings.get(
                    "ocr_verification_min_confidence",
                    DEFAULT_VISION_VERIFICATION_CONFIDENCE,
                ),
                default=DEFAULT_VISION_VERIFICATION_CONFIDENCE,
                minimum=0.50,
                maximum=0.99,
            )
        )
        self._update_verification_controls()
        self._auto_copy_cb.setChecked(
            self._normalize_bool_setting(self._settings.get("auto_copy", True), default=True)
        )
        self._show_notification_cb.setChecked(
            self._normalize_bool_setting(
                self._settings.get("show_notification", True),
                default=True,
            )
        )
        self._start_minimized_cb.setChecked(
            self._normalize_bool_setting(
                self._settings.get("start_minimized", True),
                default=True,
            )
        )
        self._cache_enabled_cb.setChecked(
            self._normalize_bool_setting(self._settings.get("cache_enabled", True), default=True)
        )
        self._cache_size_spin.setValue(
            self._normalize_int_setting(
                self._settings.get("cache_size_mb", 500),
                default=500,
                minimum=16,
                maximum=4096,
            )
        )
        self._refresh_cache_stats()

        self._japreader_autolaunch_cb.setChecked(
            self._normalize_bool_setting(
                self._settings.get("japreader_autolaunch", False),
                default=False,
            )
        )
        behavior = normalize_post_capture_behavior(self._settings)
        behavior_index = self._japreader_behavior_combo.findData(behavior)
        self._japreader_behavior_combo.setCurrentIndex(max(0, behavior_index))
        mode = self._normalize_string_setting(
            self._settings.get("japreader_integration_mode", INTEGRATION_DIRECT),
            INTEGRATION_DIRECT,
        )
        mode_index = self._japreader_mode_combo.findData(mode)
        self._japreader_mode_combo.setCurrentIndex(max(0, mode_index))
        self._japreader_send_cb.setChecked(
            self._normalize_bool_setting(
                self._settings.get("japreader_send_on_ocr", True),
                default=True,
            )
        )
        self._japreader_fallback_cb.setChecked(
            self._normalize_bool_setting(
                self._settings.get("japreader_clipboard_fallback", True),
                default=True,
            )
        )
        self._on_japreader_mode_changed()
        self._refresh_japreader_runtime_status()

    def _apply_settings(self) -> None:
        """Apply settings from UI controls to settings dict."""
        self._settings["capture_hotkey"] = self._hotkey_edit.get_hotkey()
        self._settings["overlay_to_mouse_hotkey"] = self._overlay_to_mouse_hotkey_edit.get_hotkey()
        self._settings["allow_move_overlay_to_mouse_when_hidden"] = (
            self._allow_move_overlay_when_hidden_cb.isChecked()
        )
        self._settings["allow_move_overlay_to_mouse_when_locked"] = (
            self._allow_move_overlay_when_locked_cb.isChecked()
        )
        self._settings["capture_hide_delay_ms"] = self._capture_hide_delay_spin.value()
        self._settings["ocr_engine"] = self._engine_combo.currentData()
        self._settings["paddle_profile"] = (
            self._paddle_profile_combo.currentData() or DEFAULT_PADDLE_PROFILE
        )
        self._settings["preprocessing_mode"] = self._preprocess_combo.currentData()
        self._settings["auto_crop"] = self._auto_crop_cb.isChecked()
        self._settings["detect_orientation"] = self._detect_orientation_cb.isChecked()
        self._settings["post_correction_enabled"] = self._post_correction_cb.isChecked()
        self._settings["ocr_comparison_mode"] = self._comparison_mode_combo.currentData()
        self._settings["ocr_comparison_engine"] = self._comparison_engine_combo.currentData()
        self._settings["ocr_verification_mode"] = self._verification_mode_combo.currentData()
        self._settings["ocr_verification_model"] = normalize_verification_model(
            self._verification_model_edit.text()
        )
        self._settings["ocr_verification_min_confidence"] = (
            self._verification_confidence_spin.value()
        )
        self._settings["keep_inactive_ocr_engines_warm"] = (
            self._keep_inactive_engines_warm_cb.isChecked()
        )
        self._settings["auto_copy"] = self._auto_copy_cb.isChecked()
        self._settings["show_notification"] = self._show_notification_cb.isChecked()
        self._settings["start_minimized"] = self._start_minimized_cb.isChecked()
        self._settings["cache_enabled"] = self._cache_enabled_cb.isChecked()
        self._settings["cache_size_mb"] = self._cache_size_spin.value()

        self._settings["japreader_autolaunch"] = self._japreader_autolaunch_cb.isChecked()
        self._settings["japreader_post_capture_behavior"] = (
            self._japreader_behavior_combo.currentData() or POST_CAPTURE_REVEAL
        )
        self._settings.pop("japreader_focus_after_ocr", None)
        self._settings["japreader_path"] = self._japreader_path_edit.text().strip()
        self._settings["japreader_integration_mode"] = (
            self._japreader_mode_combo.currentData() or INTEGRATION_DIRECT
        )
        self._settings["japreader_send_on_ocr"] = self._japreader_send_cb.isChecked()
        self._settings["japreader_clipboard_fallback"] = (
            self._japreader_fallback_cb.isChecked()
        )
        self._settings.pop("japreader_stop_on_exit", None)

        self.settingsChanged.emit(self._settings)
        self._refresh_cache_stats()
        QTimer.singleShot(500, self._refresh_japreader_runtime_status)

    def _ok_clicked(self) -> None:
        self._apply_settings()
        self.accept()

    # =========================================================================
    # Engine / Cache / japReader Helpers
    # =========================================================================

    def _on_engine_change(self, index: int) -> None:
        self._update_engine_description()
        self._update_paddle_profile_ui()

    def _update_engine_description(self) -> None:
        engine_value = self._engine_combo.currentData()
        try:
            engine = OCREngine(engine_value)
            self._engine_desc_label.setText(get_engine_description(engine))
        except (ValueError, KeyError):
            self._engine_desc_label.setText("")

    def _update_paddle_profile_ui(self) -> None:
        is_paddle = self._engine_combo.currentData() == OCREngine.PADDLE_OCR.value
        self._paddle_profile_combo.setEnabled(is_paddle)

        profile = self._paddle_profile_combo.currentData() or DEFAULT_PADDLE_PROFILE
        description = get_paddle_profile_description(profile)
        if not is_paddle:
            description = f"{description} Applies only when PaddleOCR is selected."
        self._paddle_profile_desc_label.setText(description)

    def _update_comparison_controls(self) -> None:
        mode = normalize_comparison_mode(self._comparison_mode_combo.currentData())
        comparison_enabled = mode != "off"
        self._comparison_engine_combo.setEnabled(comparison_enabled)

    def _update_verification_controls(self) -> None:
        mode = normalize_verification_mode(self._verification_mode_combo.currentData())
        verification_enabled = mode != "off"
        self._verification_model_edit.setEnabled(verification_enabled)
        self._verification_confidence_spin.setEnabled(verification_enabled)

    def _detect_japreader_ui(self) -> None:
        """Detect japReader and update UI."""
        saved_path = self._normalize_string_setting(self._settings.get("japreader_path", ""))
        if saved_path:
            self._japreader_path_edit.setText(saved_path)
        else:
            self._refresh_japreader_status("")

    def _browse_japreader_path(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Locate japReader",
            os.path.expanduser("~"),
            "Executable (*.exe);;All Files (*.*)"
        )
        if file_path:
            self._japreader_path_edit.setText(file_path)

    def _launch_japreader(self) -> None:
        if self._japreader_mode_combo.currentData() == INTEGRATION_DIRECT:
            self._apply_settings()
            self._japreader_runtime_status_label.setText(
                "Starting managed local japReader..."
            )
            self._japreader_runtime_status_label.setStyleSheet(
                SETTINGS_MUTED_LABEL_STYLE
            )
            QTimer.singleShot(1000, self._refresh_japreader_runtime_status)
            return
        path = self._resolve_japreader_launch_path()
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "Cannot Launch",
                                "japReader executable not found.\nPlease browse to the correct location.")
            return

        if launch_japreader(path):
            self._japreader_status_label.setText("japReader launched")
            self._japreader_status_label.setStyleSheet(SETTINGS_SUCCESS_LABEL_STYLE)
        else:
            QMessageBox.critical(self, "Launch Failed", "Failed to launch japReader.")

    def _refresh_cache_stats(self) -> None:
        try:
            cache = get_ocr_cache()
            stats = cache.get_stats()
            if stats["enabled"]:
                self._cache_stats_label.setText(
                    f"Entries: {stats['entries']} | "
                    f"Size: {stats['size_mb']}MB | "
                    f"Hit rate: {stats['hit_rate']}%"
                )
            else:
                self._cache_stats_label.setText("Cache disabled")
        except Exception as e:
            self._cache_stats_label.setText(f"Error: {e}")

    def _clear_cache(self) -> None:
        reply = QMessageBox.question(
            self, "Clear Cache",
            "Clear all cached OCR results?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                cleared = get_ocr_cache().clear()
                self._refresh_cache_stats()
                if cleared:
                    QMessageBox.information(self, "Cache Cleared", "OCR cache has been cleared.")
                else:
                    QMessageBox.warning(
                        self,
                        "Cache Unavailable",
                        "OCR cache is not currently initialized.",
                    )
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to clear cache: {e}")

    def _normalize_capture_hide_delay_ms(self, value: object) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = self.DEFAULT_CAPTURE_HIDE_DELAY_MS
        return max(self.MIN_CAPTURE_HIDE_DELAY_MS, min(self.MAX_CAPTURE_HIDE_DELAY_MS, parsed))

    def _normalize_bool_setting(self, value: object, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off", ""}:
                return False
            return default
        if isinstance(value, (int, float)):
            return bool(value)
        return default

    def _normalize_int_setting(
        self,
        value: object,
        default: int,
        minimum: int,
        maximum: Optional[int] = None,
    ) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        parsed = max(minimum, parsed)
        if maximum is not None:
            parsed = min(maximum, parsed)
        return parsed

    def _normalize_float_setting(
        self,
        value: object,
        default: float,
        minimum: float,
        maximum: Optional[float] = None,
    ) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = default
        parsed = max(minimum, parsed)
        if maximum is not None:
            parsed = min(maximum, parsed)
        return parsed

    def _normalize_string_setting(self, value: object, default: str = "") -> str:
        return value.strip() if isinstance(value, str) else default

    def _on_japreader_path_changed(self, text: str) -> None:
        self._refresh_japreader_status(text)

    def _on_japreader_mode_changed(self) -> None:
        mode = self._japreader_mode_combo.currentData() or INTEGRATION_DIRECT
        enabled = mode != INTEGRATION_DISABLED
        direct = mode == INTEGRATION_DIRECT
        self._japreader_send_cb.setEnabled(enabled)
        self._japreader_autolaunch_cb.setEnabled(enabled)
        self._japreader_behavior_combo.setEnabled(enabled)
        self._japreader_fallback_cb.setEnabled(direct)
        self._japreader_path_edit.setEnabled(enabled)
        self._japreader_launch_btn.setText(
            "Apply to connect" if direct else "Launch japReader"
        )
        self._refresh_japreader_status(self._japreader_path_edit.text())
        self._refresh_japreader_runtime_status()

    def _refresh_japreader_status(self, explicit_path: str) -> None:
        normalized_path = self._normalize_string_setting(explicit_path)
        explicit_path_exists = bool(normalized_path) and os.path.isfile(normalized_path)

        if explicit_path_exists:
            self._detected_japreader_path = normalized_path
            self._japreader_status_label.setText("japReader found")
            self._japreader_status_label.setStyleSheet(SETTINGS_SUCCESS_LABEL_STYLE)
            self._japreader_launch_btn.setEnabled(True)
            return

        if normalized_path:
            self._detected_japreader_path = ""
            self._japreader_status_label.setText("Selected path not found")
            self._japreader_status_label.setStyleSheet(SETTINGS_WARNING_LABEL_STYLE)
            self._japreader_launch_btn.setEnabled(False)
            return

        mode = self._japreader_mode_combo.currentData() or INTEGRATION_DIRECT
        detector = (
            detect_managed_japreader
            if mode == INTEGRATION_DIRECT
            else detect_japreader
        )
        self._detected_japreader_path = detector("") or ""
        if self._detected_japreader_path:
            label = (
                "Local japReader package detected"
                if mode == INTEGRATION_DIRECT
                else "japReader auto-detected"
            )
            self._japreader_status_label.setText(label)
            self._japreader_status_label.setStyleSheet(SETTINGS_SUCCESS_LABEL_STYLE)
            self._japreader_launch_btn.setEnabled(True)
        else:
            self._japreader_status_label.setText("japReader not found - browse to locate")
            self._japreader_status_label.setStyleSheet(SETTINGS_WARNING_LABEL_STYLE)
            self._japreader_launch_btn.setEnabled(False)

        if mode == INTEGRATION_DIRECT and self._detected_japreader_path:
            self._japreader_launch_btn.setEnabled(True)
        elif mode == INTEGRATION_DISABLED:
            self._japreader_launch_btn.setEnabled(False)

    def _refresh_japreader_runtime_status(self) -> None:
        if self._japreader_status_provider is None:
            self._japreader_runtime_status_label.setText(
                "Runtime status is available after the main window starts integration."
            )
            self._japreader_runtime_status_label.setStyleSheet(
                SETTINGS_MUTED_LABEL_STYLE
            )
            return
        try:
            status = self._japreader_status_provider()
            state = str(getattr(status, "state", "unknown"))
            message = str(getattr(status, "message", "Status unavailable"))
            self._japreader_runtime_status_label.setText(message)
            if state == "connected":
                style = SETTINGS_SUCCESS_LABEL_STYLE
            elif state in {"error", "parser_unavailable", "fallback"}:
                style = SETTINGS_WARNING_LABEL_STYLE
            else:
                style = SETTINGS_MUTED_LABEL_STYLE
            self._japreader_runtime_status_label.setStyleSheet(style)
        except Exception as exc:
            log_debug(f"Failed to read japReader runtime status: {exc}")
            self._japreader_runtime_status_label.setText("Runtime status unavailable")
            self._japreader_runtime_status_label.setStyleSheet(
                SETTINGS_WARNING_LABEL_STYLE
            )

    def _resolve_japreader_launch_path(self) -> str:
        explicit_path = self._normalize_string_setting(self._japreader_path_edit.text())
        if explicit_path and os.path.isfile(explicit_path):
            return explicit_path
        if not explicit_path and self._detected_japreader_path:
            return self._detected_japreader_path
        return ""

    def get_settings(self) -> dict:
        return self._settings.copy()
