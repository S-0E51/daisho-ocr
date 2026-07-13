"""
Hotkey Manager - Global keyboard and mouse hotkey registration.

Uses `pynput` for global keyboard monitoring and modifier tracking.
Mouse button hotkeys continue to use the `mouse` package so Windows
side-button bindings (`mouse4`/`mouse5`) keep working.
"""

from __future__ import annotations

from typing import Optional, Callable

from ..utils.logger import log_info, log_error, log_warning, log_debug, log_exception


class HotkeyManager:
    """Manages global keyboard and mouse hotkey registration."""

    MODIFIER_NAMES = {"ctrl", "alt", "shift", "win"}
    MOUSE_BUTTON_NAMES = {"mouse4", "mouse5", "middle"}

    def __init__(self) -> None:
        self._keyboard_registered = False
        self._mouse_registered = False
        self._keyboard_listener = None
        self._mouse_hook = None
        self._required_modifiers: set[str] = set()
        self._required_key: Optional[str] = None
        self._mouse_button: Optional[str] = None
        self._pressed_modifiers: set[str] = set()
        self._pressed_keys: set[str] = set()
        self._keyboard_triggered = False
        self._mouse_press_active = False
        self._callback: Optional[Callable] = None
        self._press_callback: Optional[Callable] = None
        self._release_callback: Optional[Callable] = None

    def register(
        self,
        hotkey: object,
        callback: Callable,
        default_hotkey: str = "ctrl+shift",
        on_pressed: Optional[Callable] = None,
        on_released: Optional[Callable] = None,
    ) -> None:
        """Register a hotkey (keyboard or mouse) with a callback."""
        if not isinstance(default_hotkey, str) or not default_hotkey.strip():
            default_hotkey = "ctrl+shift"

        if not isinstance(hotkey, str):
            log_warning(f"Non-string hotkey detected: {hotkey!r}, using default {default_hotkey}")
            hotkey = default_hotkey

        hotkey = hotkey.strip()
        if hotkey == "":
            log_warning(f"No hotkey configured, using default {default_hotkey}")
            hotkey = default_hotkey

        hotkey_lower = hotkey.lower()
        invalid_patterns = ["press key", "click to record", "mouse button..."]
        if any(pattern in hotkey_lower for pattern in invalid_patterns):
            log_warning(f"Invalid hotkey detected: '{hotkey}', using default {default_hotkey}")
            hotkey = default_hotkey
            hotkey_lower = hotkey.lower()

        self.unregister_all()
        self._callback = callback
        self._press_callback = on_pressed
        self._release_callback = on_released

        is_mouse = any(mb in hotkey_lower for mb in self.MOUSE_BUTTON_NAMES)
        if is_mouse:
            self._register_mouse(hotkey_lower)
        else:
            self._register_keyboard(hotkey_lower)

    def unregister_all(self) -> None:
        """Unregister only the hotkeys registered by this manager."""
        if self._keyboard_listener is not None:
            try:
                self._keyboard_listener.stop()
                self._keyboard_listener = None
                log_debug("Stopped pynput keyboard listener")
            except Exception as e:
                log_warning(f"Failed to stop pynput keyboard listener: {e}")

        if self._mouse_registered:
            try:
                import mouse

                if self._mouse_hook is not None:
                    mouse.unhook(self._mouse_hook)
                    self._mouse_hook = None
                log_debug("Unhooked mouse hotkey")
            except Exception as e:
                log_warning(f"Failed to unhook mouse hotkey: {e}")

        self._keyboard_registered = False
        self._mouse_registered = False
        self._required_modifiers.clear()
        self._required_key = None
        self._mouse_button = None
        self._pressed_modifiers.clear()
        self._pressed_keys.clear()
        self._keyboard_triggered = False
        self._mouse_press_active = False
        self._callback = None
        self._press_callback = None
        self._release_callback = None

    def _parse_hotkey(self, hotkey: str) -> tuple[set[str], Optional[str], list[str]]:
        """Split a hotkey string into modifiers and non-modifier parts."""
        parts = [part.strip().lower() for part in hotkey.split("+") if part.strip()]
        modifiers = {part for part in parts if part in self.MODIFIER_NAMES}
        keys = [part for part in parts if part not in self.MODIFIER_NAMES]
        return modifiers, (keys[0] if keys else None), keys

    def _register_keyboard(self, hotkey: str) -> None:
        """Register a keyboard-based hotkey using pynput."""
        try:
            modifiers, key, extra_keys = self._parse_hotkey(hotkey)
            if len(extra_keys) > 1:
                log_warning(
                    f"Hotkey '{hotkey}' contains multiple non-modifier keys; "
                    f"using '{extra_keys[0]}' only"
                )

            self._required_modifiers = modifiers
            self._required_key = key
            self._mouse_button = None
            self._pressed_modifiers.clear()
            self._pressed_keys.clear()
            self._keyboard_triggered = False

            if not self._required_modifiers and self._required_key is None:
                raise ValueError(f"Could not parse keyboard hotkey: {hotkey}")

            self._start_keyboard_listener()
            self._keyboard_registered = True
            log_info(f"Global keyboard hotkey registered with pynput: {hotkey}")

        except ImportError:
            log_warning("pynput module not installed. Global keyboard hotkeys disabled.")
        except Exception as e:
            log_error(f"Could not set up pynput keyboard hotkey: {e}")
            log_exception(e, "_register_keyboard")

    def _register_mouse(self, hotkey: str) -> None:
        """Register a mouse button-based hotkey."""
        try:
            import mouse as mouse_lib

            modifiers, key, extra_keys = self._parse_hotkey(hotkey)
            if len(extra_keys) > 1:
                log_warning(
                    f"Mouse hotkey '{hotkey}' contains multiple mouse/button tokens; "
                    f"using '{extra_keys[0]}' only"
                )

            if key not in self.MOUSE_BUTTON_NAMES:
                raise ValueError(f"Could not parse mouse button from hotkey: {hotkey}")

            self._required_modifiers = modifiers
            self._required_key = None
            self._mouse_button = {
                "mouse4": "x",
                "mouse5": "x2",
                "middle": "middle",
            }[key]
            self._pressed_modifiers.clear()
            self._pressed_keys.clear()
            self._keyboard_triggered = False
            self._mouse_press_active = False

            if self._required_modifiers:
                self._start_keyboard_listener()

            def mouse_callback(event):
                if not isinstance(event, mouse_lib.ButtonEvent):
                    return
                if event.button != self._mouse_button:
                    return

                if event.event_type == "down":
                    if not self._required_modifiers.issubset(self._pressed_modifiers):
                        return
                    self._mouse_press_active = True
                    if self._uses_press_release_callbacks():
                        log_debug(f"Mouse hotkey pressed: {hotkey}")
                        self._on_pressed()
                    return

                if event.event_type != "up":
                    return

                if self._uses_press_release_callbacks():
                    if not self._mouse_press_active:
                        return
                    self._mouse_press_active = False
                    log_debug(f"Mouse hotkey released: {hotkey}")
                    self._on_released()
                    return

                # Trigger on button release to avoid racing overlay repaint/hide.
                if not self._required_modifiers.issubset(self._pressed_modifiers):
                    return
                log_debug(f"Mouse hotkey triggered: {hotkey}")
                self._on_triggered()

            self._mouse_hook = mouse_lib.hook(mouse_callback)
            self._mouse_registered = True
            log_info(f"Global mouse hotkey registered: {hotkey}")

        except ImportError:
            log_warning("mouse module not installed. Mouse hotkeys disabled.")
        except Exception as e:
            log_error(f"Could not set up mouse hotkey: {e}")
            log_exception(e, "_register_mouse")

    def _start_keyboard_listener(self) -> None:
        """Start a pynput keyboard listener for combo tracking."""
        if self._keyboard_listener is not None:
            return

        from pynput import keyboard as pynput_keyboard

        self._keyboard_listener = pynput_keyboard.Listener(
            on_press=self._on_keyboard_press,
            on_release=self._on_keyboard_release,
        )
        self._keyboard_listener.start()

    def _on_keyboard_press(self, key) -> None:
        """Track currently pressed keys and trigger when combo becomes active."""
        name = self._normalize_keyboard_key(key)
        if name is None:
            return

        if name in self.MODIFIER_NAMES:
            self._pressed_modifiers.add(name)
        else:
            self._pressed_keys.add(name)

        if self._is_keyboard_combo_active():
            if not self._keyboard_triggered:
                self._keyboard_triggered = True
                if self._uses_press_release_callbacks():
                    log_debug("Keyboard hotkey pressed via pynput")
                    self._on_pressed()
                else:
                    log_debug("Keyboard hotkey triggered via pynput")
                    self._on_triggered()
        else:
            self._keyboard_triggered = False

    def _on_keyboard_release(self, key) -> None:
        """Release tracked keys and re-arm the combo when it becomes inactive."""
        name = self._normalize_keyboard_key(key)
        if name is None:
            return

        if name in self.MODIFIER_NAMES:
            self._pressed_modifiers.discard(name)
        else:
            self._pressed_keys.discard(name)

        if not self._is_keyboard_combo_active():
            if self._keyboard_triggered and self._uses_press_release_callbacks():
                log_debug("Keyboard hotkey released via pynput")
                self._on_released()
            self._keyboard_triggered = False

    def _normalize_keyboard_key(self, key) -> Optional[str]:
        """Convert pynput key objects to the app's hotkey token format."""
        try:
            from pynput import keyboard as pynput_keyboard
        except ImportError:
            return None

        if isinstance(key, pynput_keyboard.KeyCode):
            if key.char is None:
                return None
            return key.char.lower()

        if not isinstance(key, pynput_keyboard.Key):
            return None

        name = key.name
        if name is None:
            return None

        modifier_map = {
            "alt": "alt",
            "alt_l": "alt",
            "alt_r": "alt",
            "alt_gr": "alt",
            "ctrl": "ctrl",
            "ctrl_l": "ctrl",
            "ctrl_r": "ctrl",
            "shift": "shift",
            "shift_l": "shift",
            "shift_r": "shift",
            "cmd": "win",
            "cmd_l": "win",
            "cmd_r": "win",
        }
        if name in modifier_map:
            return modifier_map[name]

        special_map = {
            "space": "space",
            "enter": "enter",
            "tab": "tab",
            "esc": "esc",
            "backspace": "backspace",
            "delete": "delete",
            "up": "up",
            "down": "down",
            "left": "left",
            "right": "right",
            "home": "home",
            "end": "end",
            "page_up": "pageup",
            "page_down": "pagedown",
            "insert": "insert",
        }
        if name in special_map:
            return special_map[name]

        if name.startswith("f") and name[1:].isdigit():
            return name

        return name.replace("_", "")

    def _is_keyboard_combo_active(self) -> bool:
        """Return True when the required keyboard combo is currently pressed."""
        if not self._required_modifiers.issubset(self._pressed_modifiers):
            return False
        if self._required_key is None:
            return bool(self._required_modifiers)
        return self._required_key in self._pressed_keys

    def _on_triggered(self) -> None:
        """Called when hotkey is triggered."""
        if self._callback:
            self._callback()

    def _on_pressed(self) -> None:
        """Called when a press/release-aware hotkey becomes active."""
        if self._press_callback:
            self._press_callback()

    def _on_released(self) -> None:
        """Called when a press/release-aware hotkey is released."""
        if self._release_callback:
            self._release_callback()

    def _uses_press_release_callbacks(self) -> bool:
        """Return True when the caller wants press and release events."""
        return self._press_callback is not None or self._release_callback is not None
