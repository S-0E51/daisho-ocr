"""
Main Window - Primary application window with results display and controls.

Orchestrates the overlay, OCR pipeline, hotkeys, tray, and settings.
"""

from __future__ import annotations
from dataclasses import dataclass
import importlib.util
import json
import os
import queue
import threading
import time
import uuid
from typing import Optional
from PIL import Image

from ..utils import BASE_DIR
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QPlainTextEdit, QStatusBar, QLayout,
    QSystemTrayIcon, QGroupBox, QComboBox,
    QMessageBox, QApplication
)
from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtGui import QTextCursor, QCursor

from ..capture.overlay import CaptureWindow
from ..correction import TEXT_CORRECTION_CACHE_TAG, get_text_corrector
from ..ocr.comparison import (
    OCRCandidate,
    compare_candidates,
    get_comparison_engine_label,
    get_comparison_mode_label,
    normalize_comparison_engine,
    normalize_comparison_mode,
    resolve_comparison_engine,
    should_run_comparison,
)
from ..ocr.manager import get_ocr_manager, OCREngine, get_engine_name
from ..ocr.paddle_engine import (
    DEFAULT_PADDLE_PROFILE,
    get_paddle_profile_name,
    normalize_paddle_profile,
)
from ..ocr.vision_verifier import (
    DEFAULT_GEMMA_VISION_MODEL,
    DEFAULT_VISION_VERIFICATION_CONFIDENCE,
    apply_verification_result,
    get_gemma_vision_verifier,
    get_verification_mode_label,
    normalize_verification_mode,
    normalize_verification_model,
    should_run_visual_verification,
)
from ..ocr.cache import get_ocr_cache
from ..processing.image_ops import (
    PreprocessingMode, TextOrientation, mode_description, smart_preprocess, get_available_modes,
    auto_crop_text,
)
from ..integration.clipboard import copy_text
from ..integration.japreader_manager import (
    INTEGRATION_DIRECT,
    POST_CAPTURE_FOCUS,
    POST_CAPTURE_HIDDEN,
    POST_CAPTURE_REVEAL,
    JapReaderDelivery,
    JapReaderManager,
    JapReaderStatus,
    normalize_post_capture_behavior,
)
from ..utils.logger import log_info, log_error, log_warning, log_debug, log_exception
from .theme import (
    MAIN_WINDOW_STYLE,
    MAIN_STATUS_BASE_STYLE,
    MAIN_STATUS_SUCCESS_STYLE,
    MAIN_STATUS_ERROR_STYLE,
    MAIN_AUX_LABEL_STYLE,
)
from .hotkeys import HotkeyManager
from .tray import TRAY_STATUS_BUSY, TRAY_STATUS_READY, TrayManager


@dataclass(frozen=True)
class CaptureJob:
    """Immutable snapshot of the OCR context for a queued capture."""

    image: Image.Image
    engine: OCREngine
    paddle_profile: str
    preprocessing_mode: str
    auto_crop: bool
    detect_orientation: bool
    post_correction_enabled: bool
    ocr_comparison_mode: str
    ocr_comparison_engine: str
    ocr_verification_mode: str
    ocr_verification_model: str
    ocr_verification_min_confidence: float
    cache_enabled: bool
    cache_expiry_days: int


@dataclass(frozen=True)
class OCRResultPayload:
    """Structured OCR result delivered back to the UI thread."""

    text: str
    orientation: str = TextOrientation.UNKNOWN
    from_cache: bool = False
    corrections: tuple[str, ...] = ()
    comparison_notes: tuple[str, ...] = ()
    source_engine: Optional[OCREngine] = None


class MainWindow(QMainWindow):
    """Main application window."""

    CAPTURE_QUEUE_SIZE = 2
    RESULTS_CHAR_LIMIT = 30000
    WINDOW_FIT_DEBOUNCE_MS = 80
    OVERLAY_TO_MOUSE_HOLD_THRESHOLD_MS = 500
    LEGACY_CACHE_ENTRY_ESTIMATE_BYTES = 500 * 1024
    SECONDARY_ENGINE_LOAD_TIMEOUT_SEC = 12.0
    FAILED_OPTIONAL_ENGINE_RETRY_SEC = 180.0
    OCR_CACHE_PIPELINE_VERSION = "pipeline-v2"

    ocrCompleted = pyqtSignal(object)
    ocrError = pyqtSignal(str)
    triggerCapture = pyqtSignal()
    triggerOverlayToMousePressed = pyqtSignal()
    triggerOverlayToMouseReleased = pyqtSignal()
    modelLoadCompleted = pyqtSignal(object, bool, object)
    japreaderStatusChanged = pyqtSignal(object)
    japreaderDeliveryCompleted = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        log_debug("MainWindow.__init__ starting")

        self._settings = self._get_default_settings()
        self._overlay: Optional[CaptureWindow] = None
        self._tray: Optional[TrayManager] = None
        self._hotkey_mgr = HotkeyManager()
        self._overlay_to_mouse_hotkey_mgr = HotkeyManager()
        self._statusbar: Optional[QStatusBar] = None
        self._capture_btn: Optional[QPushButton] = None
        self._hotkey_label: Optional[QLabel] = None
        self._mode_label: Optional[QLabel] = None
        self._engine_chip: Optional[QLabel] = None
        self._japreader_chip: Optional[QLabel] = None
        self._japreader_toggle_btn: Optional[QPushButton] = None
        self._results_meta_label: Optional[QLabel] = None
        self._results_text: Optional[QPlainTextEdit] = None
        self._capture_queue: queue.Queue[Optional[CaptureJob]] = queue.Queue(
            maxsize=self.CAPTURE_QUEUE_SIZE
        )
        self._capture_worker_stop = threading.Event()
        self._capture_worker: Optional[threading.Thread] = None
        self._is_shutting_down = False
        self._pending_engine_unloads: set[OCREngine] = set()
        self._queued_background_warmups: list[OCREngine] = []
        self._active_background_warmup: Optional[OCREngine] = None
        self._disabled_background_warmups: set[OCREngine] = set()
        self._optional_engine_retry_after: dict[OCREngine, float] = {}
        self._optional_engine_load_errors: dict[OCREngine, str] = {}
        self._fit_window_pending_grow_only = True
        self._resources_released = False
        self._fit_window_timer = QTimer(self)
        self._fit_window_timer.setSingleShot(True)
        self._fit_window_timer.timeout.connect(self._on_fit_window_timer)
        self._overlay_to_mouse_hold_timer = QTimer(self)
        self._overlay_to_mouse_hold_timer.setSingleShot(True)
        self._overlay_to_mouse_hold_timer.timeout.connect(self._on_overlay_to_mouse_hold_timeout)
        self._overlay_to_mouse_hold_triggered = False

        self._ocr_manager = get_ocr_manager()
        self._ocr_cache = get_ocr_cache()
        self._text_corrector = get_text_corrector()

        self._load_settings()
        log_debug("Settings loaded")
        self._japreader_manager = JapReaderManager(
            self._settings,
            status_callback=self.japreaderStatusChanged.emit,
            delivery_callback=self.japreaderDeliveryCompleted.emit,
        )
        self._last_japreader_status = self._japreader_manager.get_status_snapshot()

        self._init_cache()
        log_debug("Cache initialized")

        self._setup_window()
        self._setup_ui()
        self._setup_tray()
        self._connect_signals()
        self._on_japreader_status_changed(self._last_japreader_status)
        self._setup_hotkeys()
        self._start_capture_worker()

        self._start_ocr_loading()
        self._japreader_manager.start()

        log_info("MainWindow initialization complete")

    def _get_default_settings(self) -> dict:
        return {
            "capture_hotkey": "ctrl+shift",
            "overlay_to_mouse_hotkey": "`",
            "allow_move_overlay_to_mouse_when_hidden": False,
            "allow_move_overlay_to_mouse_when_locked": False,
            "capture_hide_delay_ms": CaptureWindow.DEFAULT_CAPTURE_HIDE_DELAY_MS,
            "ocr_engine": OCREngine.PADDLE_OCR.value,
            "paddle_profile": DEFAULT_PADDLE_PROFILE,
            "preprocessing_mode": "none",
            "auto_crop": True,
            "detect_orientation": True,
            "post_correction_enabled": True,
            "ocr_comparison_mode": "off",
            "ocr_comparison_engine": "auto",
            "ocr_verification_mode": "off",
            "ocr_verification_model": DEFAULT_GEMMA_VISION_MODEL,
            "ocr_verification_min_confidence": DEFAULT_VISION_VERIFICATION_CONFIDENCE,
            "keep_inactive_ocr_engines_warm": False,
            "auto_copy": True,
            "show_notification": True,
            "start_minimized": True,
            "cache_enabled": True,
            "cache_size_mb": 500,
            "cache_expiry_days": 30,
            "overlay_geometry": None,
            "japreader_autolaunch": False,
            "japreader_post_capture_behavior": POST_CAPTURE_REVEAL,
            "japreader_path": "",
            "japreader_integration_mode": INTEGRATION_DIRECT,
            "japreader_send_on_ocr": True,
            "japreader_clipboard_fallback": True,
            "japreader_parse_timeout_sec": 12.0,
            "japreader_ichiran_command": (
                "wsl.exe -d Ubuntu -- /usr/local/bin/ichiran-cli-wsl"
            ),
            "japreader_ichiran_service_command": (
                "wsl.exe -d Ubuntu -- /usr/local/bin/ichiran-service-wsl"
            ),
        }

    def _load_settings(self) -> None:
        settings_file = os.path.join(BASE_DIR, "ocr_settings.json")
        if os.path.exists(settings_file):
            try:
                with open(settings_file, "r") as f:
                    loaded = json.load(f)
                    if not isinstance(loaded, dict):
                        raise ValueError("Settings file must contain a JSON object")
                    if (
                        "japreader_post_capture_behavior" not in loaded
                        and "japreader_focus_after_ocr" in loaded
                    ):
                        legacy_focus = self._coerce_bool_setting(
                            loaded.get("japreader_focus_after_ocr"),
                            False,
                        )
                        loaded["japreader_post_capture_behavior"] = (
                            POST_CAPTURE_FOCUS
                            if legacy_focus
                            else POST_CAPTURE_HIDDEN
                        )
                    loaded.pop("japreader_focus_after_ocr", None)
                    loaded.pop("japreader_stop_on_exit", None)
                    self._settings.update(loaded)
                    log_info(f"Settings loaded: hotkey={self._settings.get('capture_hotkey')}")
            except Exception as e:
                log_error(f"Failed to load settings: {e}")

            # Migrate deprecated preprocessing modes to "none"
            mode = self._settings.get("preprocessing_mode", "none")
            if mode in ("minimal", "advanced"):
                log_warning(f"Preprocessing mode '{mode}' is deprecated, migrating to 'none'")
                self._settings["preprocessing_mode"] = "none"

        self._sanitize_settings()

        self._settings["paddle_profile"] = self._ocr_manager.set_paddle_profile(
            self._settings.get("paddle_profile", DEFAULT_PADDLE_PROFILE)
        )

        engine_value = self._settings.get("ocr_engine", OCREngine.PADDLE_OCR.value)
        try:
            engine = OCREngine(engine_value)
            self._ocr_manager.set_engine(engine)
            log_info(f"OCR engine set to: {get_engine_name(engine)}")
        except ValueError:
            log_warning(f"Unknown OCR engine: {engine_value}, using default")
            self._ocr_manager.set_engine(OCREngine.PADDLE_OCR)

    def _init_cache(self) -> None:
        self._configure_cache_from_settings()

    def _setup_window(self) -> None:
        self.setWindowTitle("代書 - Japanese OCR")
        self.setMinimumSize(640, 520)
        self.resize(800, 650)
        self.setStyleSheet(MAIN_WINDOW_STYLE)

    def _setup_ui(self) -> None:
        central = QWidget()
        central.setObjectName("rootContainer")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(12)

        # Hero panel
        hero_panel = QWidget()
        hero_panel.setObjectName("heroPanel")
        hero_layout = QVBoxLayout(hero_panel)
        hero_layout.setContentsMargins(16, 14, 16, 14)
        hero_layout.setSpacing(8)

        hero_top = QHBoxLayout()
        hero_title = QLabel("代書")
        hero_title.setObjectName("heroTitle")
        hero_top.addWidget(hero_title)

        hero_top.addStretch()
        self._japreader_chip = QLabel("japReader: Starting")
        self._japreader_chip.setObjectName("chip")
        hero_top.addWidget(self._japreader_chip)
        self._engine_chip = QLabel("")
        self._engine_chip.setObjectName("chip")
        hero_top.addWidget(self._engine_chip)
        hero_layout.addLayout(hero_top)

        hero_subtitle = QLabel(
            "Capture Japanese text quickly with an overlay and keep results ready for paste."
        )
        hero_subtitle.setObjectName("heroSubtitle")
        hero_subtitle.setWordWrap(True)
        hero_layout.addWidget(hero_subtitle)

        hero_steps = QLabel(
            "Workflow: 1) Show Overlay  2) Position capture box  3) Press hotkey or Capture Now"
        )
        hero_steps.setObjectName("stepText")
        hero_steps.setWordWrap(True)
        hero_layout.addWidget(hero_steps)
        layout.addWidget(hero_panel)

        # Session + actions row
        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        status_group = QGroupBox("Session")
        status_layout = QVBoxLayout(status_group)
        status_layout.setSpacing(6)

        self._status_label = QLabel("Loading OCR model...")
        self._status_label.setStyleSheet(MAIN_STATUS_BASE_STYLE)
        status_layout.addWidget(self._status_label)

        self._gpu_label = QLabel("")
        self._gpu_label.setObjectName("statusMuted")
        self._gpu_label.setStyleSheet(MAIN_AUX_LABEL_STYLE)
        status_layout.addWidget(self._gpu_label)

        self._hotkey_label = QLabel("")
        self._hotkey_label.setObjectName("statusMuted")
        self._hotkey_label.setStyleSheet(MAIN_AUX_LABEL_STYLE)
        status_layout.addWidget(self._hotkey_label)

        self._mode_label = QLabel("")
        self._mode_label.setObjectName("statusMuted")
        self._mode_label.setStyleSheet(MAIN_AUX_LABEL_STYLE)
        status_layout.addWidget(self._mode_label)
        top_row.addWidget(status_group, 1)

        actions_group = QGroupBox("Quick Actions")
        actions_layout = QVBoxLayout(actions_group)
        actions_layout.setSpacing(8)

        actions_hint = QLabel(
            "Overlay is required for capture. Use Settings to customize hotkeys and behavior."
        )
        actions_hint.setObjectName("sectionHint")
        actions_hint.setWordWrap(True)
        actions_layout.addWidget(actions_hint)

        primary_actions = QHBoxLayout()
        primary_actions.setSpacing(8)

        self._show_overlay_btn = QPushButton("Show Overlay")
        self._show_overlay_btn.setObjectName("primary")
        self._show_overlay_btn.clicked.connect(self._show_overlay)
        primary_actions.addWidget(self._show_overlay_btn)

        self._capture_btn = QPushButton("Capture Now")
        self._capture_btn.setObjectName("secondary")
        self._capture_btn.clicked.connect(self._manual_capture)
        self._capture_btn.setEnabled(False)
        primary_actions.addWidget(self._capture_btn)
        actions_layout.addLayout(primary_actions)

        secondary_actions = QHBoxLayout()
        secondary_actions.setSpacing(8)

        self._hide_overlay_btn = QPushButton("Hide Overlay")
        self._hide_overlay_btn.setObjectName("ghost")
        self._hide_overlay_btn.clicked.connect(self._hide_overlay)
        self._hide_overlay_btn.setEnabled(False)
        secondary_actions.addWidget(self._hide_overlay_btn)

        self._japreader_toggle_btn = QPushButton("Show japReader")
        self._japreader_toggle_btn.setObjectName("ghost")
        self._japreader_toggle_btn.clicked.connect(self._toggle_japreader)
        secondary_actions.addWidget(self._japreader_toggle_btn)

        settings_btn = QPushButton("Settings")
        settings_btn.setObjectName("secondary")
        settings_btn.clicked.connect(self._show_settings)
        secondary_actions.addWidget(settings_btn)
        actions_layout.addLayout(secondary_actions)
        top_row.addWidget(actions_group, 1)

        layout.addLayout(top_row)

        # Preprocessing mode
        preprocess_group = QGroupBox("Preprocessing")
        preprocess_layout = QHBoxLayout(preprocess_group)
        preprocess_layout.setSpacing(8)

        preprocess_label = QLabel("Mode:")
        preprocess_label.setObjectName("sectionHint")
        preprocess_layout.addWidget(preprocess_label)

        self._preprocess_combo = QComboBox()
        for mode in get_available_modes():
            self._preprocess_combo.addItem(mode_description(mode), mode.value)
        self._preprocess_combo.currentIndexChanged.connect(self._on_preprocess_change)

        saved_mode = self._settings.get("preprocessing_mode", "none")
        index = self._preprocess_combo.findData(saved_mode)
        if index >= 0:
            self._preprocess_combo.setCurrentIndex(index)

        preprocess_layout.addWidget(self._preprocess_combo, 1)
        layout.addWidget(preprocess_group)

        # Results
        results_group = QGroupBox("OCR Results")
        results_layout = QVBoxLayout(results_group)
        results_layout.setSpacing(8)

        results_header = QHBoxLayout()
        results_header.setSpacing(8)

        results_hint = QLabel("Captured text output")
        results_hint.setStyleSheet("font-size: 13px; font-weight: 600;")
        results_header.addWidget(results_hint)

        results_header.addStretch()

        self._results_meta_label = QLabel("No results yet")
        self._results_meta_label.setObjectName("resultsMeta")
        results_header.addWidget(self._results_meta_label)
        results_layout.addLayout(results_header)

        self._results_text = QPlainTextEdit()
        self._results_text.setObjectName("resultsArea")
        hotkey = self._settings.get("capture_hotkey", "ctrl+shift")
        self._results_text.setPlaceholderText(
            "OCR results will appear here...\n\n"
            "Tips:\n"
            "1. Click Show Overlay to display the capture region.\n"
            "2. Position and resize the overlay over Japanese text.\n"
            f"3. Press the capture hotkey ({hotkey}) or click Capture Now."
        )
        self._results_text.textChanged.connect(self._update_results_meta)
        results_layout.addWidget(self._results_text)

        result_buttons = QHBoxLayout()
        result_buttons.setSpacing(8)

        copy_btn = QPushButton("Copy All")
        copy_btn.setObjectName("secondary")
        copy_btn.clicked.connect(self._copy_results)
        result_buttons.addWidget(copy_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("ghost")
        clear_btn.clicked.connect(self._clear_results)
        result_buttons.addWidget(clear_btn)
        result_buttons.addStretch()

        results_layout.addLayout(result_buttons)
        layout.addWidget(results_group, 1)

        # Status bar
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._statusbar.showMessage("Ready")

        self._update_capture_controls(overlay_visible=False)
        self._refresh_session_labels()
        self._update_results_meta()
        self._fit_window_to_content(grow_only=True)

    def _fit_window_to_content(self, grow_only: bool = True) -> None:
        central = self.centralWidget()
        if central is None or central.layout() is None:
            return

        central.layout().activate()
        hint = self.sizeHint()
        if not hint.isValid():
            return

        target_w = max(780, hint.width() + 20)
        target_h = max(640, hint.height() + 20)
        self.setMinimumSize(target_w, target_h)

        if not grow_only:
            self.resize(target_w, target_h)
            return

        current = self.size()
        new_w = max(current.width(), target_w)
        new_h = max(current.height(), target_h)
        if new_w != current.width() or new_h != current.height():
            self.resize(new_w, new_h)

    def _schedule_fit_window(self, grow_only: bool = True) -> None:
        self._fit_window_pending_grow_only = self._fit_window_pending_grow_only and grow_only
        if self._fit_window_timer is None:
            self._fit_window_to_content(grow_only=grow_only)
            return
        self._fit_window_timer.start(self.WINDOW_FIT_DEBOUNCE_MS)

    def _on_fit_window_timer(self) -> None:
        grow_only = self._fit_window_pending_grow_only
        self._fit_window_pending_grow_only = True
        self._fit_window_to_content(grow_only=grow_only)

    def _start_capture_worker(self) -> None:
        if self._capture_worker is not None and self._capture_worker.is_alive():
            return

        self._capture_worker_stop.clear()
        self._capture_worker = threading.Thread(
            target=self._capture_worker_loop,
            name="ocr-capture-worker",
            daemon=True,
        )
        self._capture_worker.start()

    def _stop_capture_worker(self, timeout_sec: float = 5.0) -> bool:
        self._capture_worker_stop.set()
        while True:
            try:
                pending_job = self._capture_queue.get_nowait()
            except queue.Empty:
                break
            else:
                self._capture_queue.task_done()
                if pending_job is not None:
                    log_debug("Discarded queued capture during shutdown")
        if self._capture_worker is not None and self._capture_worker.is_alive():
            try:
                self._capture_queue.put_nowait(None)
            except queue.Full:
                pass
            self._capture_worker.join(timeout=timeout_sec)
            if self._capture_worker.is_alive():
                log_warning(
                    "Capture worker did not stop before timeout; "
                    "skipping OCR/cache teardown to avoid races during exit"
                )
                return False
        self._capture_worker = None
        return True

    def _capture_worker_loop(self) -> None:
        while not self._capture_worker_stop.is_set():
            try:
                capture_job = self._capture_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                if capture_job is None:
                    return
                if self._capture_worker_stop.is_set():
                    log_debug("Discarding capture job after shutdown request")
                    return
                self._process_capture_job(capture_job)
            finally:
                self._capture_queue.task_done()

    def _build_capture_job(self, pil_image: Image.Image) -> CaptureJob:
        """Snapshot OCR settings so queued captures remain stable across UI changes."""
        engine = self._ocr_manager.current_engine
        paddle_profile = self._ocr_manager.get_paddle_profile()
        return CaptureJob(
            image=pil_image,
            engine=engine,
            paddle_profile=paddle_profile,
            preprocessing_mode=self._settings.get("preprocessing_mode", "none"),
            auto_crop=self._settings.get("auto_crop", True),
            detect_orientation=self._settings.get("detect_orientation", True),
            post_correction_enabled=self._settings.get("post_correction_enabled", True),
            ocr_comparison_mode=normalize_comparison_mode(
                self._settings.get("ocr_comparison_mode", "off")
            ),
            ocr_comparison_engine=normalize_comparison_engine(
                self._settings.get("ocr_comparison_engine", "auto")
            ),
            ocr_verification_mode=normalize_verification_mode(
                self._settings.get("ocr_verification_mode", "off")
            ),
            ocr_verification_model=normalize_verification_model(
                self._settings.get("ocr_verification_model", DEFAULT_GEMMA_VISION_MODEL)
            ),
            ocr_verification_min_confidence=self._coerce_float_setting(
                self._settings.get(
                    "ocr_verification_min_confidence",
                    DEFAULT_VISION_VERIFICATION_CONFIDENCE,
                ),
                default=DEFAULT_VISION_VERIFICATION_CONFIDENCE,
                minimum=0.0,
                maximum=1.0,
            ),
            cache_enabled=self._settings.get("cache_enabled", True),
            cache_expiry_days=self._settings.get("cache_expiry_days", 30),
        )

    def _run_ocr_candidate(
        self,
        job: CaptureJob,
        target_engine: OCREngine,
        image: Image.Image,
    ) -> OCRCandidate:
        """Run OCR for one engine and apply the same post-correction pipeline."""
        analysis = self._ocr_manager.perform_ocr_analysis_with_engine(target_engine, image)
        raw_text = analysis.text
        final_text = raw_text
        corrections: tuple[str, ...] = ()

        post_correction_active = job.post_correction_enabled and self._text_corrector.available
        if post_correction_active and raw_text:
            correction_result = self._text_corrector.correct(raw_text)
            final_text = correction_result.text
            corrections = correction_result.corrections

        return OCRCandidate(
            engine=target_engine,
            text=final_text,
            raw_text=raw_text,
            average_confidence=analysis.average_confidence,
            corrections=corrections,
        )

    def _log_candidate_result(self, candidate: OCRCandidate, prefix: str = "OCR") -> None:
        """Write a concise OCR preview plus any corrections to the app log."""
        if candidate.text:
            preview = candidate.text[:80].replace("\n", " ")
            if len(candidate.text) > 80:
                preview += "..."
            log_info(f"{prefix} result ({get_engine_name(candidate.engine)}, {len(candidate.text)} chars): {preview}")
        else:
            log_info(f"{prefix} result ({get_engine_name(candidate.engine)}): <empty>")

        if candidate.corrections:
            log_info(
                f"{prefix} corrections ({get_engine_name(candidate.engine)}): "
                + " | ".join(
                    correction.encode("unicode_escape").decode()
                    for correction in candidate.corrections
                )
            )

    def _resolve_comparison_candidate(
        self,
        job: CaptureJob,
        processed_image: Image.Image,
        primary_candidate: OCRCandidate,
    ) -> tuple[OCRCandidate, tuple[str, ...], bool]:
        """Optionally compare the primary OCR result with a secondary engine."""
        should_compare, primary_assessment = should_run_comparison(
            job.ocr_comparison_mode,
            primary_candidate,
        )
        if not should_compare:
            return primary_candidate, (), True

        comparison_engine = resolve_comparison_engine(
            primary_candidate.engine,
            job.ocr_comparison_engine,
        )
        if comparison_engine is None:
            return primary_candidate, (
                "OCR comparison skipped: no secondary engine available for this primary engine.",
            ), True

        if not self._ocr_manager.is_engine_loaded(comparison_engine):
            blocked_note = self._optional_engine_retry_note(comparison_engine)
            if blocked_note:
                return primary_candidate, (blocked_note,), False

        success, load_error = self._ocr_manager.load_engine_blocking(
            comparison_engine,
            timeout=self.SECONDARY_ENGINE_LOAD_TIMEOUT_SEC,
        )
        if not success:
            if self._ocr_manager.is_engine_loading(comparison_engine):
                error_text = (
                    f"timed out after {self.SECONDARY_ENGINE_LOAD_TIMEOUT_SEC:.0f}s "
                    "while loading"
                )
            else:
                error_text = load_error or "unknown load error"
            self._record_optional_engine_load_failure(comparison_engine, error_text)
            return primary_candidate, (
                f"OCR comparison skipped: {get_engine_name(comparison_engine)} could not load ({error_text}).",
            ), False
        self._clear_optional_engine_load_failure(comparison_engine)

        comparison_notes: tuple[str, ...] = ()
        try:
            secondary_candidate = self._run_ocr_candidate(job, comparison_engine, processed_image)
            self._log_candidate_result(secondary_candidate, prefix="OCR comparison")
            decision = compare_candidates(primary_candidate, secondary_candidate)
            if primary_assessment.suspicious:
                comparison_notes = decision.notes + (
                    "Primary OCR looked suspicious: "
                    + ", ".join(primary_assessment.suspicious_reasons),
                )
            else:
                comparison_notes = decision.notes
            return decision.selected, comparison_notes, True
        finally:
            if not self._keep_inactive_engines_warm() and comparison_engine != self._ocr_manager.current_engine:
                self._ocr_manager.unload_engine(comparison_engine)

    def _resolve_visual_verification_candidate(
        self,
        job: CaptureJob,
        processed_image: Image.Image,
        selected_candidate: OCRCandidate,
    ) -> tuple[OCRCandidate, tuple[str, ...], bool]:
        """Optionally verify the selected OCR text against the image with Gemma."""
        should_verify, verification_reasons = should_run_visual_verification(
            job.ocr_verification_mode,
            selected_candidate,
        )
        if not should_verify:
            return selected_candidate, (), True

        verifier = get_gemma_vision_verifier()
        if not verifier.is_loaded or verifier.model_id != job.ocr_verification_model:
            if verifier.is_loading:
                note = "Vision verification skipped: Gemma verifier is still loading in the background."
                log_info(note)
                return selected_candidate, (note,), False

            can_retry, retry_message = verifier.can_retry_load(job.ocr_verification_model)
            if not can_retry:
                note = f"Vision verification skipped: {retry_message}"
                log_info(note)
                return selected_candidate, (note,), False

            verifier.load_model_async(job.ocr_verification_model)
            note = "Vision verification skipped: Gemma verifier is loading in the background."
            log_info(note)
            return selected_candidate, (note,), False

        try:
            verification = verifier.verify(
                processed_image,
                selected_candidate.text,
                model_id=job.ocr_verification_model,
            )
        except Exception as exc:
            log_warning(f"Vision verification skipped: {exc}")
            return selected_candidate, (f"Vision verification skipped: {exc}",), False

        decision = apply_verification_result(
            selected_candidate,
            verification,
            min_confidence=job.ocr_verification_min_confidence,
        )

        notes = list(decision.notes)
        if verification_reasons:
            notes.append(
                "Vision verification triggered: " + ", ".join(verification_reasons)
            )
        for note in notes:
            log_info(note)
        return decision.selected, tuple(notes), True

    def _process_capture_job(self, job: CaptureJob) -> None:
        try:
            pil_image = job.image
            engine_name = get_engine_name(job.engine)
            mode_str = job.preprocessing_mode
            auto_crop = job.auto_crop
            cache_enabled = job.cache_enabled
            crop_cache_tag = "smart-v2" if auto_crop else "off"
            correction_cache_tag = (
                TEXT_CORRECTION_CACHE_TAG
                if job.post_correction_enabled and self._text_corrector.available
                else "off"
            )
            comparison_cache_tag = job.ocr_comparison_mode
            if comparison_cache_tag != "off":
                comparison_cache_tag = f"{comparison_cache_tag}:{job.ocr_comparison_engine}"
            verification_cache_tag = job.ocr_verification_mode
            if verification_cache_tag != "off":
                verification_cache_tag = (
                    f"{verification_cache_tag}:{job.ocr_verification_model}"
                    f":{job.ocr_verification_min_confidence:.2f}"
                )
            cache_engine_key = (
                f"{self.OCR_CACHE_PIPELINE_VERSION}:{engine_name}"
                f":paddle={job.paddle_profile}:{mode_str}"
                f":crop={crop_cache_tag}:corr={correction_cache_tag}"
                f":cmp={comparison_cache_tag}:verify={verification_cache_tag}"
            )

            cache_key = ""
            if cache_enabled:
                cached_result, cache_key = self._ocr_cache.get_with_key(
                    pil_image, engine=cache_engine_key
                )
                if cached_result:
                    self.ocrCompleted.emit(
                        OCRResultPayload(
                            text=cached_result,
                            from_cache=True,
                        )
                    )
                    return

            try:
                mode = PreprocessingMode(mode_str)
            except ValueError:
                log_warning(f"Unknown preprocessing mode '{mode_str}', using NONE")
                mode = PreprocessingMode.NONE

            original_size = pil_image.size
            crop_source = ""
            crop_input = pil_image
            if auto_crop:
                if job.engine == OCREngine.PADDLE_OCR:
                    detected_crop, crop_box = self._ocr_manager.crop_image_to_text_with_engine(
                        job.engine,
                        pil_image,
                    )
                    if crop_box is not None and detected_crop.size != original_size:
                        crop_input = detected_crop
                        crop_source = "Paddle text detection"

                if crop_input.size == original_size:
                    contour_crop = auto_crop_text(pil_image)
                    if contour_crop.size != original_size:
                        crop_input = contour_crop
                        crop_source = "contour fallback"

            processed, orientation = smart_preprocess(
                crop_input,
                auto_crop=False,
                detect_orientation=job.detect_orientation,
                preprocessing_mode=mode
            )

            if auto_crop and crop_input.size != original_size:
                log_info(f"Auto-cropped ({crop_source}): {original_size} -> {crop_input.size}")
            if job.detect_orientation and orientation != TextOrientation.UNKNOWN:
                log_info(f"Detected text orientation: {orientation}")

            primary_candidate = self._run_ocr_candidate(job, job.engine, processed)
            self._log_candidate_result(primary_candidate)
            selected_candidate, comparison_notes, comparison_cacheable = self._resolve_comparison_candidate(
                job,
                processed,
                primary_candidate,
            )
            selected_candidate, verification_notes, verification_cacheable = self._resolve_visual_verification_candidate(
                job,
                processed,
                selected_candidate,
            )
            result = selected_candidate.text
            corrections = selected_candidate.corrections

            pipeline_cacheable = comparison_cacheable and verification_cacheable
            if cache_enabled and result and pipeline_cacheable:
                self._ocr_cache.store_with_key(
                    cache_key,
                    result,
                    expiry_days=job.cache_expiry_days,
                )
            elif cache_enabled and result:
                log_debug("Skipping OCR cache store because optional OCR stages did not complete")

            self.ocrCompleted.emit(
                OCRResultPayload(
                    text=result,
                    orientation=orientation,
                    corrections=corrections,
                    comparison_notes=comparison_notes + verification_notes,
                    source_engine=selected_candidate.engine,
                )
            )

        except Exception as e:
            log_exception(e, "_process_capture_job")
            self.ocrError.emit(str(e))

    def _setup_tray(self) -> None:
        self._tray = TrayManager(
            parent=self,
            on_show_window=self.show,
            on_show_overlay=self._show_overlay,
            on_hide_overlay=self._hide_overlay,
            on_show_japreader=self._show_japreader,
            on_hide_japreader=self._hide_japreader,
            on_settings=self._show_settings,
            on_reload=self._reload_app,
            on_quit=self._quit,
            on_engine_selected=self._on_engine_selected,
            on_tray_activated=self._on_tray_activated,
        )
        self._tray.update_engine_check(self._ocr_manager.current_engine)
        self._refresh_tray_status()

    def _set_tray_status(self, status: str, detail: str = "") -> None:
        if self._tray:
            self._tray.update_status(status, detail)

    def _refresh_tray_status(self) -> None:
        if not self._tray:
            return

        engine = self._ocr_manager.current_engine
        engine_name = get_engine_name(engine)
        if self._ocr_manager.is_engine_loaded(engine):
            self._set_tray_status(TRAY_STATUS_READY, f"{engine_name} ready")
        elif self._ocr_manager.is_engine_loading(engine):
            self._set_tray_status(TRAY_STATUS_BUSY, f"Loading {engine_name}")
        elif self._ocr_manager.load_error:
            self._set_tray_status(TRAY_STATUS_BUSY, f"{engine_name} issue")
        else:
            self._set_tray_status(TRAY_STATUS_BUSY, f"{engine_name} not ready")

    def _connect_signals(self) -> None:
        self.ocrCompleted.connect(self._on_ocr_complete)
        self.ocrError.connect(self._on_ocr_error)
        self.triggerCapture.connect(self._do_capture_from_hotkey)
        self.triggerOverlayToMousePressed.connect(self._begin_overlay_to_mouse_hold)
        self.triggerOverlayToMouseReleased.connect(self._finish_overlay_to_mouse_hold)
        self.modelLoadCompleted.connect(self._update_model_status)
        self.japreaderStatusChanged.connect(self._on_japreader_status_changed)
        self.japreaderDeliveryCompleted.connect(self._on_japreader_delivery_completed)

    def _setup_hotkeys(self) -> None:
        capture_hotkey = self._settings.get("capture_hotkey", "ctrl+shift")
        overlay_to_mouse_hotkey = self._settings.get("overlay_to_mouse_hotkey", "`")
        self._hotkey_mgr.register(
            capture_hotkey,
            self._on_hotkey_pressed,
            default_hotkey="ctrl+shift",
        )
        self._overlay_to_mouse_hotkey_mgr.register(
            overlay_to_mouse_hotkey,
            self._on_overlay_to_mouse_hotkey_pressed,
            default_hotkey="`",
            on_pressed=self._on_overlay_to_mouse_hotkey_pressed,
            on_released=self._on_overlay_to_mouse_hotkey_released,
        )
        self._refresh_session_labels()

    def _sanitize_settings(self) -> None:
        boolean_defaults = {
            "allow_move_overlay_to_mouse_when_hidden": False,
            "allow_move_overlay_to_mouse_when_locked": False,
            "auto_crop": True,
            "detect_orientation": True,
            "post_correction_enabled": True,
            "keep_inactive_ocr_engines_warm": False,
            "auto_copy": True,
            "show_notification": True,
            "start_minimized": True,
            "cache_enabled": True,
            "japreader_autolaunch": False,
            "japreader_send_on_ocr": True,
            "japreader_clipboard_fallback": True,
        }
        for key, default in boolean_defaults.items():
            self._settings[key] = self._coerce_bool_setting(self._settings.get(key, default), default)

        string_defaults = {
            "capture_hotkey": "ctrl+shift",
            "overlay_to_mouse_hotkey": "`",
            "ocr_engine": OCREngine.PADDLE_OCR.value,
            "paddle_profile": DEFAULT_PADDLE_PROFILE,
            "preprocessing_mode": "none",
            "ocr_comparison_mode": "off",
            "ocr_comparison_engine": "auto",
            "ocr_verification_mode": "off",
            "ocr_verification_model": DEFAULT_GEMMA_VISION_MODEL,
            "japreader_path": "",
            "japreader_integration_mode": INTEGRATION_DIRECT,
            "japreader_post_capture_behavior": POST_CAPTURE_REVEAL,
            "japreader_ichiran_command": (
                "wsl.exe -d Ubuntu -- /usr/local/bin/ichiran-cli-wsl"
            ),
            "japreader_ichiran_service_command": (
                "wsl.exe -d Ubuntu -- /usr/local/bin/ichiran-service-wsl"
            ),
        }
        for key, default in string_defaults.items():
            self._settings[key] = self._coerce_string_setting(self._settings.get(key, default), default)
        self._settings["ocr_comparison_mode"] = normalize_comparison_mode(
            self._settings.get("ocr_comparison_mode", "off")
        )
        self._settings["ocr_comparison_engine"] = normalize_comparison_engine(
            self._settings.get("ocr_comparison_engine", "auto")
        )
        self._settings["ocr_verification_mode"] = normalize_verification_mode(
            self._settings.get("ocr_verification_mode", "off")
        )
        self._settings["ocr_verification_model"] = normalize_verification_model(
            self._settings.get("ocr_verification_model", DEFAULT_GEMMA_VISION_MODEL)
        )
        self._settings["paddle_profile"] = normalize_paddle_profile(
            self._settings.get("paddle_profile", DEFAULT_PADDLE_PROFILE)
        )
        if self._settings["japreader_integration_mode"] not in {
            "direct",
            "legacy",
            "disabled",
        }:
            self._settings["japreader_integration_mode"] = INTEGRATION_DIRECT
        self._settings["japreader_post_capture_behavior"] = (
            normalize_post_capture_behavior(self._settings)
        )
        self._settings.pop("japreader_focus_after_ocr", None)
        self._settings.pop("japreader_stop_on_exit", None)
        self._settings["japreader_parse_timeout_sec"] = self._coerce_float_setting(
            self._settings.get("japreader_parse_timeout_sec", 12.0),
            default=12.0,
            minimum=2.0,
            maximum=60.0,
        )

        overlay_geometry = self._settings.get("overlay_geometry")
        self._settings["overlay_geometry"] = overlay_geometry if isinstance(overlay_geometry, str) else None
        self._settings["capture_hide_delay_ms"] = self._normalized_capture_hide_delay_ms()
        self._settings["cache_size_mb"] = self._coerce_int_setting(
            self._settings.get("cache_size_mb", self._legacy_cache_size_mb()),
            default=500,
            minimum=16,
        )
        self._settings["cache_expiry_days"] = self._coerce_int_setting(
            self._settings.get("cache_expiry_days", 30),
            default=30,
            minimum=1,
        )
        self._settings["ocr_verification_min_confidence"] = self._coerce_float_setting(
            self._settings.get(
                "ocr_verification_min_confidence",
                DEFAULT_VISION_VERIFICATION_CONFIDENCE,
            ),
            default=DEFAULT_VISION_VERIFICATION_CONFIDENCE,
            minimum=0.0,
            maximum=1.0,
        )

    def _coerce_bool_setting(self, value: object, default: bool) -> bool:
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

    def _coerce_string_setting(self, value: object, default: str) -> str:
        return value.strip() if isinstance(value, str) else default

    def _coerce_int_setting(self, value: object, default: int, minimum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return max(minimum, parsed)

    def _coerce_float_setting(
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

    def _normalized_capture_hide_delay_ms(self) -> int:
        try:
            parsed = int(
                self._settings.get(
                    "capture_hide_delay_ms",
                    CaptureWindow.DEFAULT_CAPTURE_HIDE_DELAY_MS,
                )
            )
        except (TypeError, ValueError):
            parsed = CaptureWindow.DEFAULT_CAPTURE_HIDE_DELAY_MS

        return max(
            CaptureWindow.MIN_CAPTURE_HIDE_DELAY_MS,
            min(CaptureWindow.MAX_CAPTURE_HIDE_DELAY_MS, parsed),
        )

    def _apply_overlay_capture_delay_setting(self) -> None:
        delay_ms = self._normalized_capture_hide_delay_ms()
        self._settings["capture_hide_delay_ms"] = delay_ms
        if self._overlay is not None:
            self._overlay.set_capture_hide_delay_ms(delay_ms)

    def _legacy_cache_size_mb(self) -> int:
        """Convert the old cache_max_entries setting to the explicit MB setting."""
        max_entries = self._coerce_int_setting(
            self._settings.get("cache_max_entries", 1000),
            default=1000,
            minimum=1,
        )
        size_bytes = max_entries * self.LEGACY_CACHE_ENTRY_ESTIMATE_BYTES
        return max(16, int(round(size_bytes / (1024 * 1024))))

    def _cache_settings_signature(self) -> tuple[bool, int]:
        return (
            self._settings.get("cache_enabled", True),
            self._settings.get("cache_size_mb", 500),
        )

    def _configure_cache_from_settings(self) -> None:
        cache_enabled, cache_size_mb = self._cache_settings_signature()
        max_size = cache_size_mb * 1024 * 1024
        self._ocr_cache.initialize(
            cache_dir=os.path.join(BASE_DIR, "ocr_cache"),
            max_size=max_size,
            enabled=cache_enabled,
        )

    def _persist_window_state(self) -> None:
        if self._overlay:
            self._settings["overlay_geometry"] = self._overlay.save_geometry_string()
        self._save_settings()

    def _refresh_session_labels(self) -> None:
        if self._engine_chip is not None:
            engine_name = get_engine_name(self._ocr_manager.current_engine)
            if self._ocr_manager.current_engine == OCREngine.PADDLE_OCR:
                profile_name = get_paddle_profile_name(self._ocr_manager.get_paddle_profile())
                engine_name = f"{engine_name} ({profile_name})"
            self._engine_chip.setText(f"Engine: {engine_name}")

        if self._hotkey_label is not None:
            capture_hotkey = self._settings.get("capture_hotkey", "ctrl+shift")
            overlay_to_mouse_hotkey = self._settings.get("overlay_to_mouse_hotkey", "`")
            self._hotkey_label.setText(
                f"Hotkeys: capture {capture_hotkey} | move overlay {overlay_to_mouse_hotkey}"
            )

        if self._mode_label is not None:
            mode_key = self._settings.get("preprocessing_mode", "none")
            try:
                mode = PreprocessingMode(mode_key)
                mode_text = mode_description(mode)
            except ValueError:
                mode_text = mode_key
            comparison_mode = normalize_comparison_mode(
                self._settings.get("ocr_comparison_mode", "off")
            )
            comparison_text = f"Compare: {get_comparison_mode_label(comparison_mode)}"
            if comparison_mode != "off":
                comparison_engine = normalize_comparison_engine(
                    self._settings.get("ocr_comparison_engine", "auto")
                )
                comparison_text += f" via {get_comparison_engine_label(comparison_engine)}"
            verification_mode = normalize_verification_mode(
                self._settings.get("ocr_verification_mode", "off")
            )
            verification_text = f"Verify: {get_verification_mode_label(verification_mode)}"
            if verification_mode != "off":
                verification_model = normalize_verification_model(
                    self._settings.get("ocr_verification_model", DEFAULT_GEMMA_VISION_MODEL)
                )
                verification_text += f" via {verification_model}"
            self._mode_label.setText(
                f"Preprocessing: {mode_text} | {comparison_text} | {verification_text}"
            )
        self._schedule_fit_window(grow_only=True)

    def _update_capture_controls(self, overlay_visible: bool) -> None:
        self._show_overlay_btn.setEnabled(not overlay_visible)
        self._hide_overlay_btn.setEnabled(overlay_visible)
        if self._capture_btn is not None:
            capture_enabled = overlay_visible
            if capture_enabled and self._overlay is not None:
                capture_enabled = self._overlay.hotkey_enabled
            self._capture_btn.setEnabled(capture_enabled)

    def _update_results_meta(self) -> None:
        if self._results_meta_label is None or self._results_text is None:
            return

        doc = self._results_text.document()
        char_count = max(0, doc.characterCount() - 1)
        if char_count == 0:
            self._results_meta_label.setText("No results yet")
            return

        line_count = doc.blockCount()
        self._results_meta_label.setText(f"{char_count} chars · {line_count} lines")

    def _append_results_entry(self, text: str) -> None:
        self._results_text.appendPlainText(text)
        self._trim_results_text()

    def _trim_results_text(self) -> None:
        doc = self._results_text.document()
        char_count = max(0, doc.characterCount() - 1)
        if char_count <= self.RESULTS_CHAR_LIMIT:
            return

        keep_from = int(self.RESULTS_CHAR_LIMIT * 0.75)
        chars_to_remove = max(0, char_count - keep_from)
        if chars_to_remove <= 0:
            return

        trim_pos = 0
        block = doc.begin()
        while block.isValid() and chars_to_remove > 0:
            block_len = max(1, block.length())
            chars_to_remove -= block_len
            trim_pos = block.position() + block_len
            block = block.next()

        if trim_pos <= 0:
            return

        self._results_text.blockSignals(True)

        trim_cursor = QTextCursor(doc)
        trim_cursor.setPosition(0)
        trim_cursor.setPosition(trim_pos, QTextCursor.MoveMode.KeepAnchor)
        trim_cursor.removeSelectedText()

        # Remove leading empty blocks left by block-boundary trimming.
        while doc.blockCount() > 1 and not doc.begin().text().strip():
            cleanup = QTextCursor(doc)
            cleanup.setPosition(doc.begin().position())
            cleanup.movePosition(
                QTextCursor.MoveOperation.NextBlock,
                QTextCursor.MoveMode.KeepAnchor
            )
            cleanup.removeSelectedText()

        self._results_text.blockSignals(False)

        cursor = self._results_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._results_text.setTextCursor(cursor)
        self._update_results_meta()

    def _on_hotkey_pressed(self) -> None:
        if self._is_shutting_down:
            log_debug("Ignoring capture hotkey during shutdown")
            return
        log_debug("Hotkey pressed, emitting triggerCapture signal")
        self.triggerCapture.emit()

    def _on_overlay_to_mouse_hotkey_pressed(self) -> None:
        if self._is_shutting_down:
            log_debug("Ignoring overlay-to-mouse hotkey during shutdown")
            return
        log_debug("Overlay-to-mouse hotkey pressed")
        self.triggerOverlayToMousePressed.emit()

    def _on_overlay_to_mouse_hotkey_released(self) -> None:
        if self._is_shutting_down:
            log_debug("Ignoring overlay-to-mouse hotkey release during shutdown")
            return
        log_debug("Overlay-to-mouse hotkey released")
        self.triggerOverlayToMouseReleased.emit()

    def _begin_overlay_to_mouse_hold(self) -> None:
        if self._is_shutting_down:
            log_debug("Ignoring overlay-to-mouse hold start during shutdown")
            return

        self._overlay_to_mouse_hold_triggered = False
        self._overlay_to_mouse_hold_timer.start(self.OVERLAY_TO_MOUSE_HOLD_THRESHOLD_MS)

    def _finish_overlay_to_mouse_hold(self) -> None:
        if self._is_shutting_down:
            log_debug("Ignoring overlay-to-mouse hold finish during shutdown")
            return

        if self._overlay_to_mouse_hold_timer.isActive():
            self._overlay_to_mouse_hold_timer.stop()

        if self._overlay_to_mouse_hold_triggered:
            self._overlay_to_mouse_hold_triggered = False
            return

        self._move_overlay_to_mouse_from_hotkey()

    def _on_overlay_to_mouse_hold_timeout(self) -> None:
        if self._is_shutting_down:
            log_debug("Ignoring overlay-to-mouse hold timeout during shutdown")
            return

        self._overlay_to_mouse_hold_triggered = True
        self._disable_and_hide_overlay_from_hold()

    def _do_capture_from_hotkey(self) -> None:
        if self._is_shutting_down:
            log_debug("Ignoring capture request during shutdown")
            return
        overlay = self._overlay
        if overlay is None or not overlay.isVisible():
            log_info("Capture hotkey ignored because overlay is hidden")
            if self._statusbar:
                self._statusbar.showMessage("Capture is disabled while the overlay is hidden.")
            return

        if overlay.hotkey_enabled:
            log_info("Triggering capture from hotkey")
            overlay.capture_region()
        else:
            log_info("Capture hotkey ignored because overlay capture is paused")
            if self._statusbar:
                self._statusbar.showMessage("Capture is paused. Click the overlay toggle to resume.")

    def _manual_capture(self) -> None:
        overlay = self._overlay
        if overlay is None or not overlay.isVisible():
            log_info("Manual capture ignored because overlay is hidden")
            if self._statusbar:
                self._statusbar.showMessage("Capture is disabled while the overlay is hidden.")
            return
        if not overlay.hotkey_enabled:
            log_info("Manual capture ignored because overlay capture is paused")
            if self._statusbar:
                self._statusbar.showMessage("Capture is paused. Click the overlay toggle to resume.")
            return

        overlay.capture_region()

    def _start_ocr_loading(self) -> None:
        engine = self._ocr_manager.current_engine
        engine_name = get_engine_name(engine)
        if self._ocr_manager.is_loaded:
            self._status_label.setText(f"Activating cached {engine_name}...")
            self._set_tray_status(TRAY_STATUS_READY, f"{engine_name} ready")
        elif self._ocr_manager.is_engine_loading(engine):
            self._status_label.setText(f"Finishing load for {engine_name}...")
            self._set_tray_status(TRAY_STATUS_BUSY, f"Loading {engine_name}")
        else:
            self._status_label.setText(f"Loading {engine_name}...")
            self._set_tray_status(TRAY_STATUS_BUSY, f"Loading {engine_name}")
        self._status_label.setStyleSheet(MAIN_STATUS_BASE_STYLE)
        self._refresh_session_labels()
        self._ocr_manager.load_engine_async(
            engine,
            lambda success, error, requested_engine=engine: self._dispatch_model_load_result(
                requested_engine,
                success,
                error,
            )
        )

    def _keep_inactive_engines_warm(self) -> bool:
        return self._settings.get("keep_inactive_ocr_engines_warm", False)

    def _optional_engine_retry_note(self, engine: OCREngine) -> str:
        retry_after = self._optional_engine_retry_after.get(engine, 0.0)
        if retry_after <= time.monotonic():
            return ""
        retry_in = max(1, int(retry_after - time.monotonic()))
        error_text = self._optional_engine_load_errors.get(engine, "previous load failure")
        return (
            f"OCR comparison skipped: {get_engine_name(engine)} recently failed to load; "
            f"retrying in {retry_in}s ({error_text})."
        )

    def _record_optional_engine_load_failure(self, engine: OCREngine, error_text: str) -> None:
        self._optional_engine_retry_after[engine] = (
            time.monotonic() + self.FAILED_OPTIONAL_ENGINE_RETRY_SEC
        )
        self._optional_engine_load_errors[engine] = error_text

    def _clear_optional_engine_load_failure(self, engine: OCREngine) -> None:
        self._optional_engine_retry_after.pop(engine, None)
        self._optional_engine_load_errors.pop(engine, None)

    def _clear_background_warmups(self) -> None:
        self._queued_background_warmups.clear()
        if (
            self._active_background_warmup is not None
            and self._active_background_warmup != self._ocr_manager.current_engine
        ):
            self._pending_engine_unloads.add(self._active_background_warmup)

    def _can_background_warm_engine(self, engine: OCREngine) -> bool:
        if engine in self._disabled_background_warmups:
            return False
        if engine == OCREngine.RAPID_OCR:
            return importlib.util.find_spec("rapidocr") is not None
        if engine == OCREngine.SURYA:
            return importlib.util.find_spec("surya") is not None
        return True

    def _queue_background_warmups(self) -> None:
        if self._is_shutting_down or not self._keep_inactive_engines_warm():
            return

        current_engine = self._ocr_manager.current_engine
        self._queued_background_warmups = [
            engine
            for engine in self._ocr_manager.ALL_ENGINES
            if engine != current_engine
            and engine != self._active_background_warmup
            and self._can_background_warm_engine(engine)
            and not self._ocr_manager.is_engine_loaded(engine)
            and not self._ocr_manager.is_engine_loading(engine)
        ]
        self._start_next_background_warmup()

    def _start_next_background_warmup(self) -> None:
        if self._is_shutting_down or not self._keep_inactive_engines_warm():
            return
        if self._active_background_warmup is not None:
            return

        while self._queued_background_warmups:
            engine = self._queued_background_warmups.pop(0)
            if engine == self._ocr_manager.current_engine:
                continue
            if not self._can_background_warm_engine(engine):
                continue
            if self._ocr_manager.is_engine_loaded(engine) or self._ocr_manager.is_engine_loading(engine):
                continue
            if self._optional_engine_retry_after.get(engine, 0.0) > time.monotonic():
                continue

            self._active_background_warmup = engine
            log_info(f"Background warming {get_engine_name(engine)}...")
            self._ocr_manager.load_engine_async(
                engine,
                lambda success, error, requested_engine=engine: self._dispatch_model_load_result(
                    requested_engine,
                    success,
                    error,
                ),
            )
            return

    def _trim_inactive_engine_residency(self) -> None:
        current_engine = self._ocr_manager.current_engine
        for engine in self._ocr_manager.ALL_ENGINES:
            if engine == current_engine:
                continue
            if self._ocr_manager.is_engine_loading(engine):
                self._pending_engine_unloads.add(engine)
                continue
            if self._ocr_manager.is_engine_loaded(engine):
                self._ocr_manager.unload_engine(engine)

    def _handle_engine_load_completion(
        self,
        engine: OCREngine,
        success: bool,
        error: Optional[str],
    ) -> None:
        was_background_warmup = engine == self._active_background_warmup
        if was_background_warmup:
            self._active_background_warmup = None
            if success:
                self._clear_optional_engine_load_failure(engine)
                log_info(f"Background warm complete: {get_engine_name(engine)}")
            else:
                self._disabled_background_warmups.add(engine)
                self._record_optional_engine_load_failure(
                    engine,
                    error or "unknown error",
                )
                log_warning(
                    f"Background warm failed for {get_engine_name(engine)}: "
                    f"{error or 'unknown error'}"
                )

        if engine in self._pending_engine_unloads:
            self._pending_engine_unloads.discard(engine)
            if success and engine != self._ocr_manager.current_engine:
                self._ocr_manager.unload_engine(engine)

        if not success:
            if self._keep_inactive_engines_warm():
                self._start_next_background_warmup()
            return

        if engine == self._ocr_manager.current_engine:
            if self._keep_inactive_engines_warm():
                self._queue_background_warmups()
            else:
                self._clear_background_warmups()
                self._trim_inactive_engine_residency()
        elif self._keep_inactive_engines_warm():
            self._start_next_background_warmup()

    def _dispatch_model_load_result(
        self,
        engine: OCREngine,
        success: bool,
        error: Optional[str],
    ) -> None:
        if self._is_shutting_down:
            log_debug(f"Ignoring {get_engine_name(engine)} load callback during shutdown")
            return

        try:
            self.modelLoadCompleted.emit(engine, success, error)
        except RuntimeError as exc:
            log_debug(f"Ignoring late model-load callback after window teardown: {exc}")

    def _update_model_status(self, engine: OCREngine, success: bool, error: Optional[str]) -> None:
        if self._is_shutting_down:
            log_debug(f"Ignoring {get_engine_name(engine)} status update during shutdown")
            return

        self._handle_engine_load_completion(engine, success, error)

        if engine != self._ocr_manager.current_engine:
            log_debug(f"Ignoring stale OCR load callback for {get_engine_name(engine)}")
            return

        engine_name = get_engine_name(engine)
        if success:
            self._status_label.setText(f"Ready - {engine_name} loaded")
            self._status_label.setStyleSheet(MAIN_STATUS_SUCCESS_STYLE)
            self._set_tray_status(TRAY_STATUS_READY, f"{engine_name} ready")
            self._gpu_label.setText(
                "GPU acceleration enabled" if self._ocr_manager.uses_gpu else "Running on CPU"
            )
        else:
            error_text = error or f"{engine_name} failed to load"
            self._status_label.setText(f"Error: {error_text}")
            self._status_label.setStyleSheet(MAIN_STATUS_ERROR_STYLE)
            self._set_tray_status(TRAY_STATUS_BUSY, f"{engine_name} issue")
        self._schedule_fit_window(grow_only=True)

    def _on_engine_selected(self, engine: OCREngine) -> None:
        if engine == self._ocr_manager.current_engine:
            return

        was_cached = self._ocr_manager.is_engine_loaded(engine)
        log_info(f"Switching OCR engine to: {get_engine_name(engine)}")
        self._clear_optional_engine_load_failure(engine)
        if not self._keep_inactive_engines_warm():
            self._clear_background_warmups()
        self._tray.update_engine_check(engine)
        self._settings["ocr_engine"] = engine.value
        self._ocr_manager.set_engine(engine)
        self._start_ocr_loading()
        self._refresh_session_labels()
        self._save_settings()

        if self._tray:
            self._tray.show_message(
                "OCR Engine Changed",
                (
                    f"Switched to cached {get_engine_name(engine)}"
                    if was_cached
                    else f"Loading {get_engine_name(engine)}..."
                )
            )

    # =========================================================================
    # Overlay Management
    # =========================================================================

    def _ensure_overlay(self) -> CaptureWindow:
        if self._overlay is None:
            self._overlay = CaptureWindow()
            self._overlay.captureCompleted.connect(self._on_capture)
            self._overlay.geometryChanged.connect(self._on_overlay_geometry_changed)
            self._overlay.overlayVisibilityChanged.connect(self._on_overlay_visibility_changed)
            self._overlay.captureAvailabilityChanged.connect(
                self._on_overlay_capture_availability_changed
            )

            if self._settings.get("overlay_geometry"):
                self._overlay.restore_geometry_string(self._settings["overlay_geometry"])

        self._apply_overlay_capture_delay_setting()
        return self._overlay

    def _show_overlay(self) -> None:
        overlay = self._ensure_overlay()

        overlay.show()
        overlay.raise_()
        overlay.activateWindow()
        self._update_capture_controls(overlay_visible=True)

    def _move_overlay_to_mouse_from_hotkey(self) -> None:
        if self._is_shutting_down:
            log_debug("Ignoring overlay-to-mouse request during shutdown")
            return

        allow_when_hidden = self._settings.get("allow_move_overlay_to_mouse_when_hidden", False)
        allow_when_locked = self._settings.get("allow_move_overlay_to_mouse_when_locked", False)

        overlay = self._overlay
        if overlay is None:
            if not allow_when_hidden:
                log_debug("Overlay is hidden, ignoring overlay-to-mouse hotkey")
                return
            overlay = self._ensure_overlay()

        if overlay.capture_in_progress:
            log_debug("Ignoring overlay-to-mouse hotkey while capture is in progress")
            return

        if not overlay.isVisible():
            is_hidden_pause_recovery = not overlay.hotkey_enabled
            if not allow_when_hidden and not is_hidden_pause_recovery:
                log_debug("Overlay is hidden, ignoring overlay-to-mouse hotkey")
                return
            if not overlay.hotkey_enabled:
                overlay.hotkey_enabled = True
            overlay.show()
            overlay.raise_()
            overlay.activateWindow()
        elif not overlay.hotkey_enabled and not allow_when_locked:
            log_debug("Capture is paused, ignoring overlay-to-mouse hotkey")
            overlay.focus_for_input()
            return

        moved = overlay.center_on_global_point(QCursor.pos())
        overlay.focus_for_input()
        self._update_capture_controls(overlay_visible=overlay.isVisible())
        if moved and self._statusbar is not None:
            self._statusbar.showMessage("Overlay centered on the cursor.")

    def _disable_and_hide_overlay_from_hold(self) -> None:
        overlay = self._overlay
        if overlay is None:
            log_debug("Overlay-to-mouse hold ignored because overlay has not been created")
            if self._statusbar is not None:
                self._statusbar.showMessage("Overlay is already hidden.")
            return

        if overlay.hotkey_enabled:
            overlay.hotkey_enabled = False

        self._hide_overlay()
        if self._statusbar is not None:
            self._statusbar.showMessage("Overlay hidden and capture paused.")

    def _hide_overlay(self) -> None:
        if self._overlay is not None:
            self._overlay.cancel_pending_capture_restore()
            self._overlay.hide()
        self._update_capture_controls(overlay_visible=False)

    def _on_overlay_geometry_changed(self, geometry) -> None:
        if self._overlay:
            self._settings["overlay_geometry"] = self._overlay.save_geometry_string()

    def _on_overlay_visibility_changed(self, is_visible: bool) -> None:
        self._update_capture_controls(overlay_visible=is_visible)

    def _on_overlay_capture_availability_changed(self, is_enabled: bool) -> None:
        overlay_visible = self._overlay is not None and self._overlay.isVisible()
        self._update_capture_controls(overlay_visible=overlay_visible)

    # =========================================================================
    # OCR Pipeline
    # =========================================================================

    def _on_capture(self, pil_image: Image.Image) -> None:
        if self._is_shutting_down:
            log_debug("Ignoring capture result during shutdown")
            return

        log_info(f"Capture received, image size: {pil_image.size}")

        if not self._ocr_manager.is_loaded:
            log_warning("OCR engine not loaded yet")
            QMessageBox.warning(self, "OCR Not Ready", "OCR model is still loading...")
            return

        if self._statusbar:
            self._statusbar.showMessage("Processing...")
        self._append_results_entry("--- Processing capture... ---")

        capture_job = self._build_capture_job(pil_image)
        try:
            self._capture_queue.put_nowait(capture_job)
        except queue.Full:
            try:
                self._capture_queue.get_nowait()
                self._capture_queue.task_done()
                self._capture_queue.put_nowait(capture_job)
                log_warning("Capture queue full - replaced oldest queued capture")
                if self._statusbar:
                    self._statusbar.showMessage("OCR busy. Updated queue with latest capture.")
                self._append_results_entry("--- OCR busy: replaced oldest queued capture ---")
                return
            except (queue.Empty, queue.Full):
                pass

            log_warning("Capture queue full - dropping newest capture")
            if self._statusbar:
                self._statusbar.showMessage("OCR busy. Wait for current capture to finish.")
            self._append_results_entry("--- OCR busy: capture skipped ---")

    def _on_ocr_complete(self, payload: object) -> None:
        if self._is_shutting_down:
            log_debug("Ignoring OCR completion during shutdown")
            return

        if isinstance(payload, OCRResultPayload):
            text = payload.text
            orientation = payload.orientation
            from_cache = payload.from_cache
            corrections = payload.corrections
            comparison_notes = payload.comparison_notes
            source_engine = payload.source_engine
        else:
            text = str(payload or "")
            orientation = TextOrientation.UNKNOWN
            from_cache = False
            corrections = ()
            comparison_notes = ()
            source_engine = None

        if text:
            if orientation != TextOrientation.UNKNOWN:
                self._append_results_entry(f"--- Text orientation: {orientation} ---")
            for note in comparison_notes:
                self._append_results_entry(note)
            if corrections:
                self._append_results_entry("Corrections: " + " | ".join(corrections))
            if source_engine is not None and source_engine != self._ocr_manager.current_engine:
                self._append_results_entry(
                    f"Selected engine: {get_engine_name(source_engine)}"
                )
            self._append_results_entry(f"Result:\n{text}\n")

            capture_id = str(uuid.uuid4())
            self._japreader_manager.submit_text(
                text,
                capture_id=capture_id,
            )

            if self._settings.get("auto_copy", True):
                if copy_text(text):
                    clipboard_message = "Cached result copied to clipboard" if from_cache else "Result copied to clipboard"
                    if corrections:
                        clipboard_message += f" ({len(corrections)} correction"
                        if len(corrections) != 1:
                            clipboard_message += "s"
                        clipboard_message += ")"
                    if source_engine is not None and source_engine != self._ocr_manager.current_engine:
                        clipboard_message += f" via {get_engine_name(source_engine)}"
                    self._statusbar.showMessage(clipboard_message)

                    if self._settings.get("show_notification", True) and self._tray:
                        display = f"Copied: {text[:50]}..." if len(text) > 50 else f"Copied: {text}"
                        self._tray.show_message("OCR Complete", display)
                else:
                    failure_message = (
                        "OCR complete (clipboard copy failed, cached result)"
                        if from_cache
                        else "OCR complete (clipboard copy failed)"
                    )
                    self._statusbar.showMessage(failure_message)
            else:
                completion_message = "OCR complete (cached result)" if from_cache else "OCR complete"
                if source_engine is not None and source_engine != self._ocr_manager.current_engine:
                    completion_message += f" via {get_engine_name(source_engine)}"
                self._statusbar.showMessage(completion_message)

        else:
            self._append_results_entry("--- No text found ---")
            self._statusbar.showMessage("No text detected")
            if self._settings.get("show_notification", True) and self._tray:
                self._tray.show_message("No Text Detected", "Capture completed, but OCR found no text.")
        self._refresh_tray_status()

    def _on_ocr_error(self, error: str) -> None:
        if self._is_shutting_down:
            log_debug(f"Ignoring OCR error during shutdown: {error}")
            return

        self._append_results_entry(f"Error: {error}")
        self._statusbar.showMessage("OCR error")
        self._set_tray_status(TRAY_STATUS_BUSY, "OCR error")
        QMessageBox.warning(self, "OCR Error", f"An error occurred:\n{error}")

    # =========================================================================
    # UI Actions
    # =========================================================================

    def _copy_results(self) -> None:
        text = self._results_text.toPlainText()
        if text:
            if copy_text(text):
                self._statusbar.showMessage("Results copied to clipboard")
            else:
                self._statusbar.showMessage("Failed to copy to clipboard")
        else:
            self._statusbar.showMessage("No results to copy")

    def _clear_results(self) -> None:
        self._results_text.clear()
        if self._statusbar:
            self._statusbar.showMessage("Results cleared")

    def _on_preprocess_change(self, index: int) -> None:
        mode = self._preprocess_combo.currentData()
        self._settings["preprocessing_mode"] = mode
        self._refresh_session_labels()
        log_debug(f"Preprocessing mode changed to: {mode}")
        if self._statusbar is not None:
            self._statusbar.showMessage(f"Preprocessing mode: {mode}")

    def _show_settings(self) -> None:
        from .settings_dialog import SettingsDialog

        dialog = SettingsDialog(
            self._settings,
            self,
            japreader_status_provider=self._japreader_manager.get_status_snapshot,
        )
        dialog.settingsChanged.connect(self._apply_settings)

        if dialog.exec():
            self._settings = dialog.get_settings()
            self._save_settings()
            self._schedule_fit_window(grow_only=True)

    def _apply_settings(self, settings: dict) -> None:
        old_hotkey = self._settings.get("capture_hotkey")
        old_overlay_to_mouse_hotkey = self._settings.get("overlay_to_mouse_hotkey")
        old_engine = self._settings.get("ocr_engine")
        old_paddle_profile = self._settings.get("paddle_profile", DEFAULT_PADDLE_PROFILE)
        old_keep_inactive_engines_warm = self._settings.get("keep_inactive_ocr_engines_warm", False)
        old_cache_signature = self._cache_settings_signature()
        old_japreader_signature = self._japreader_settings_signature()

        self._settings.update(settings)
        self._sanitize_settings()
        new_hotkey = self._settings.get("capture_hotkey")
        new_overlay_to_mouse_hotkey = self._settings.get("overlay_to_mouse_hotkey")
        new_engine = self._settings.get("ocr_engine")
        new_keep_inactive_engines_warm = self._settings.get("keep_inactive_ocr_engines_warm", False)
        self._settings["paddle_profile"] = self._ocr_manager.set_paddle_profile(
            self._settings.get("paddle_profile", DEFAULT_PADDLE_PROFILE)
        )
        self._apply_overlay_capture_delay_setting()
        if old_cache_signature != self._cache_settings_signature():
            self._configure_cache_from_settings()
        if old_japreader_signature != self._japreader_settings_signature():
            self._japreader_manager.update_settings(self._settings)

        if (
            old_hotkey != new_hotkey
            or old_overlay_to_mouse_hotkey != new_overlay_to_mouse_hotkey
        ):
            self._setup_hotkeys()

        if old_engine != new_engine:
            try:
                engine = OCREngine(new_engine)
                self._clear_optional_engine_load_failure(engine)
                self._ocr_manager.set_engine(engine)
                if self._tray:
                    self._tray.update_engine_check(engine)
                self._start_ocr_loading()
            except ValueError:
                log_warning(f"Unknown OCR engine: {new_engine}")
        elif (
            self._ocr_manager.current_engine == OCREngine.PADDLE_OCR
            and old_paddle_profile != self._settings["paddle_profile"]
        ):
            self._start_ocr_loading()
            if self._statusbar is not None:
                profile_name = get_paddle_profile_name(self._settings["paddle_profile"])
                self._statusbar.showMessage(f"Paddle mode: {profile_name}")

        if old_keep_inactive_engines_warm != new_keep_inactive_engines_warm:
            if new_keep_inactive_engines_warm:
                if self._statusbar is not None:
                    self._statusbar.showMessage("Inactive OCR engines will stay warm in memory.")
                if self._ocr_manager.is_engine_loaded(self._ocr_manager.current_engine):
                    self._queue_background_warmups()
            else:
                self._clear_background_warmups()
                if self._statusbar is not None:
                    self._statusbar.showMessage("Inactive OCR engines will lazy-load on demand.")
                if self._ocr_manager.is_engine_loaded(self._ocr_manager.current_engine):
                    self._trim_inactive_engine_residency()

        mode = settings.get("preprocessing_mode", "none")
        index = self._preprocess_combo.findData(mode)
        if index >= 0:
            self._preprocess_combo.setCurrentIndex(index)
        self._refresh_session_labels()

    def _japreader_settings_signature(self) -> tuple[object, ...]:
        return (
            self._settings.get("japreader_integration_mode"),
            self._settings.get("japreader_send_on_ocr"),
            self._settings.get("japreader_autolaunch"),
            self._settings.get("japreader_post_capture_behavior"),
            self._settings.get("japreader_clipboard_fallback"),
            self._settings.get("japreader_parse_timeout_sec"),
            self._settings.get("japreader_ichiran_command"),
            self._settings.get("japreader_ichiran_service_command"),
            self._settings.get("japreader_path"),
        )

    def _on_japreader_status_changed(self, status: object) -> None:
        if not isinstance(status, JapReaderStatus):
            return
        self._last_japreader_status = status
        log_debug(f"japReader integration state changed to {status.state}")
        if self._is_shutting_down:
            return

        visible = bool(status.reader_visible)
        direct_enabled = (
            self._settings.get("japreader_integration_mode") == INTEGRATION_DIRECT
        )
        if status.state == "disabled":
            label = "Disabled"
        elif status.state == "starting":
            label = "Starting"
        elif status.state == "connected":
            label = "Ready" if visible else "Hidden"
        else:
            label = "Unavailable"

        if self._japreader_chip is not None:
            self._japreader_chip.setText(f"japReader: {label}")
        if self._japreader_toggle_btn is not None:
            self._japreader_toggle_btn.setText(
                "Hide japReader" if visible else "Show japReader"
            )
            self._japreader_toggle_btn.setEnabled(direct_enabled)
        if self._tray is not None:
            self._tray.update_japreader_status(
                label,
                can_show=direct_enabled and not visible,
                can_hide=direct_enabled and visible,
            )

        if self._statusbar is None:
            return
        if status.state in {"error", "parser_unavailable", "fallback"}:
            self._statusbar.showMessage(status.message)

    def _toggle_japreader(self) -> None:
        if self._last_japreader_status.reader_visible:
            self._hide_japreader()
        else:
            self._show_japreader()

    def _show_japreader(self) -> None:
        queued = self._japreader_manager.show_reader(activate=True)
        if self._statusbar is not None:
            self._statusbar.showMessage(
                "Opening japReader" if queued else "japReader integration is disabled"
            )

    def _hide_japreader(self) -> None:
        queued = self._japreader_manager.hide_reader()
        if self._statusbar is not None:
            self._statusbar.showMessage(
                "Hiding japReader" if queued else "japReader integration is disabled"
            )

    def _on_japreader_delivery_completed(self, delivery: object) -> None:
        if not isinstance(delivery, JapReaderDelivery):
            return
        if self._is_shutting_down:
            return
        if self._statusbar is not None:
            self._statusbar.showMessage(delivery.message)
        if not delivery.ok:
            self._append_results_entry(f"--- japReader: {delivery.message} ---")

    def _save_settings(self) -> None:
        try:
            with open(os.path.join(BASE_DIR, "ocr_settings.json"), "w") as f:
                json.dump(self._settings, f, indent=2)
            log_info("Settings saved to ocr_settings.json")
        except Exception as e:
            log_error(f"Failed to save settings: {e}")

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            if self._overlay and self._overlay.isVisible():
                self._hide_overlay()
            else:
                self._show_overlay()

    def _reload_app(self) -> None:
        import sys
        import subprocess

        log_info("Reloading application...")
        self._persist_window_state()

        python_exe = sys.executable
        script_path = os.path.abspath(sys.argv[0])

        try:
            subprocess.Popen([python_exe, script_path])
            log_info("New instance started, exiting current instance")
        except Exception as e:
            log_error(f"Failed to start new instance: {e}")
            if self._statusbar is not None:
                self._statusbar.showMessage("Reload failed. Current instance is still running.")
            QMessageBox.warning(
                self,
                "Reload Failed",
                f"Could not start a new instance.\n\n{e}",
            )
            return

        self._is_shutting_down = True
        self._stop_capture_worker()
        self._hotkey_mgr.unregister_all()
        self._overlay_to_mouse_hotkey_mgr.unregister_all()
        self._release_runtime_resources()
        if self._tray:
            self._tray.hide()
        if self._overlay:
            self._overlay.cancel_pending_capture_restore()
            self._overlay.close()
        QApplication.quit()

    def _release_runtime_resources(self) -> None:
        if self._resources_released:
            return

        self._resources_released = True
        try:
            self._japreader_manager.close()
        except Exception as exc:
            log_warning(f"Failed to close japReader integration during shutdown: {exc}")

        try:
            self._ocr_cache.close()
        except Exception as exc:
            log_warning(f"Failed to close OCR cache during shutdown: {exc}")

        try:
            get_gemma_vision_verifier().unload_model(wait=False)
        except Exception as exc:
            log_warning(f"Failed to unload Gemma vision verifier during shutdown: {exc}")

        try:
            self._ocr_manager.unload_all(wait_timeout_sec=12.0)
        except Exception as exc:
            log_warning(f"Failed to unload OCR models during shutdown: {exc}")

    def _quit(self) -> None:
        self._is_shutting_down = True
        self._persist_window_state()

        worker_stopped = self._stop_capture_worker()
        self._hotkey_mgr.unregister_all()
        self._overlay_to_mouse_hotkey_mgr.unregister_all()
        if not worker_stopped:
            log_warning("Capture worker did not stop cleanly; forcing model cleanup during shutdown")
        self._release_runtime_resources()
        if self._tray:
            self._tray.hide()
        if self._overlay:
            self._overlay.cancel_pending_capture_restore()
            self._overlay.close()

        QApplication.quit()

    def closeEvent(self, event) -> None:
        if not self._is_shutting_down:
            self._quit()
        event.accept()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._schedule_fit_window(grow_only=True)
