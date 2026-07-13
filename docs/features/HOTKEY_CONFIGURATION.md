# Hotkey Configuration Guide

## Overview

The Japanese OCR Overlay Tool now includes a user-friendly hotkey configuration UI that allows you to customize the capture shortcut without editing configuration files.

## How to Change the Hotkey

### Method 1: Record (Recommended - Easy!)

1. **Open the main window** (right-click system tray → "Show Main Window")
2. **Locate the Settings section** at the top of the window
3. **Click the "🎙 Record Hotkey" button** (green button)
4. **Press your desired key combination** (e.g., Ctrl+Shift+F9)
   - The display updates in real-time as you press keys
   - Recording auto-stops 500ms after your last key press
   - Press ESC to cancel
5. **Click "Apply"** to save the new hotkey
6. Look for the status message:
   - ✓ Green = Success
   - ✗ Red = Failed (invalid or already in use)

### Method 2: Manual Entry (Advanced)

1. **Open the main window**
2. **Type your hotkey** directly in the text field (e.g., `ctrl+shift+f9`)
3. **Click "Apply"**
4. Check the status message

## Supported Hotkey Formats

### Modifiers
- `ctrl` - Control key
- `alt` - Alt key
- `shift` - Shift key
- `win` / `super` - Windows/Super key
- `cmd` - Command key (macOS)

### Regular Keys
- Letters: `a-z`
- Numbers: `0-9`

### Special Keys
- Function keys: `f1` - `f12`
- Arrow keys: `up`, `down`, `left`, `right`
- Navigation: `home`, `end`, `pageup`, `pagedown`
- Action keys: `space`, `enter`, `esc`, `tab`, `backspace`, `delete`

### Combination Format
Combine keys with `+` symbol:
```
modifier+modifier+key
```

## Example Hotkeys

### Single Keys
```
f9         # Function key F9
f12        # Function key F12
```

### Modifier Combinations
```
ctrl+shift       # Control + Shift (default)
ctrl+alt+c       # Control + Alt + C
alt+space        # Alt + Space
ctrl+shift+f9    # Control + Shift + F9
shift+f12        # Shift + F12
```

### Common Patterns
```
ctrl+`           # Control + Backtick
alt+q            # Alt + Q
ctrl+alt+x       # Control + Alt + X
```

## Recording Feature Details

### How Recording Works

1. **Click "Record Hotkey"** - Button turns red (⏹ Stop Recording)
2. **Press your keys** - The field updates in real-time showing what you're pressing
3. **Auto-stop** - Recording automatically stops 500ms after your last keypress
4. **Click "Apply"** - Saves and registers the new hotkey

### Real-Time Feedback

While recording, you'll see:
- Button changes: 🎙 Record Hotkey (green) → ⏹ Stop Recording (red)
- Field shows: "Press keys now..." → "ctrl+shift+f9" (live update)
- Status shows: "🎙 Recording..." (orange)

### Smart Key Normalization

The recorder automatically:
- Converts "left ctrl" / "right ctrl" → "ctrl"
- Converts "control" → "ctrl"
- Converts "windows" → "win"
- Orders modifiers correctly (ctrl+alt+shift, not shift+ctrl+alt)

### Canceling

Press **ESC** during recording to cancel and keep your current hotkey.

## Tips

1. **Use the recorder!**: Much easier than typing - just press the keys you want

2. **Avoid system hotkeys**: Don't use combinations already used by your OS
   - Windows: Avoid `win+...` combinations
   - macOS: Avoid `cmd+...` system shortcuts

3. **Test immediately**: After applying, test the hotkey with the overlay visible

4. **Keyboard module required**: Global hotkeys require the `keyboard` module
   - If not available, you'll see a warning in logs
   - The app still works, but hotkey feature will be disabled

5. **Settings auto-save**: Changed hotkeys are immediately saved to `ocr_settings.json`

6. **Revert on error**: If registration fails, the old hotkey is automatically restored

## Troubleshooting

### "Failed to register" error
- **Cause**: Hotkey already in use by another application
- **Solution**: Choose a different combination

### "Invalid hotkey format" error
- **Cause**: Unrecognized key name or invalid format
- **Solution**: Check spelling and format (use lowercase, `+` to combine)

### Hotkey not working
1. Check that the overlay window is visible (hotkey only works when overlay is shown)
2. Verify "Keyboard module available" in logs (Show Logs from tray menu)
3. Try a simpler combination like `f9` to test

### Status shows yellow button (停) on overlay
- This means hotkey capture is **paused**
- Click the button to toggle back to red (active)
- Yellow = paused, Red = active

## Configuration File

Hotkeys are stored in `ocr_settings.json`:

```json
{
  "capture_hotkey": "ctrl+shift",
  "overlay_geometry": "300x50+100+100",
  "preprocessing_mode": "none"
}
```

You can manually edit this file when the app is closed, but using the UI is recommended.

## Advanced: Mouse Button Support (Future)

Currently, only keyboard hotkeys are supported. Mouse button support (e.g., mouse button 5) requires the `mouse` module and additional implementation.

To request mouse button support, please open an issue on the project repository.

---

**Last Updated**: 2025-11-16
