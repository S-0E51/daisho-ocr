# Mouse Bindings Guide

## Overview

The Japanese OCR Overlay Tool now supports **mouse button bindings** for triggering OCR captures. You can use mouse buttons alone or combined with keyboard modifiers (Ctrl, Alt, Shift).

## Feature Status

✅ **IMPLEMENTED** - Mouse binding support is fully integrated and ready to use.

---

## Requirements

### Required Module

The `mouse` library must be installed for mouse bindings to work:

```bash
pip install mouse
```

**Verification:**
When you start the application, check for this message:
```
[OK] mouse module available
```

If you see:
```
Warning: mouse module not available (...)
```

Then run: `pip install mouse` and restart the application.

---

## Supported Mouse Buttons

| Button Name | Aliases | Physical Button |
|-------------|---------|-----------------|
| `mouse1` | `mouseleft` | Left mouse button |
| `mouse2` | `mouseright` | Right mouse button |
| `mouse3` | `mousemiddle` | Middle mouse button (scroll wheel click) |
| `mouse4` | - | Side button 1 (usually "Back") |
| `mouse5` | - | Side button 2 (usually "Forward") |

**Note:** Mouse 4 and 5 are only available on mice with side buttons (gaming mice, advanced mice, etc.)

---

## Hotkey Examples

### Mouse Only (No Keyboard Modifiers)

| Hotkey String | Description |
|---------------|-------------|
| `mouse3` | Middle mouse button (scroll wheel click) |
| `mouse4` | Side button 1 (Back) |
| `mouse5` | Side button 2 (Forward) |
| `mouseright` | Right mouse button |

### Mouse + Keyboard Modifiers

| Hotkey String | Description |
|---------------|-------------|
| `ctrl+mouse3` | Ctrl + Middle mouse button |
| `alt+mouse4` | Alt + Side button 1 |
| `shift+mouse5` | Shift + Side button 2 |
| `ctrl+shift+mouse3` | Ctrl + Shift + Middle button |
| `ctrl+alt+mouse4` | Ctrl + Alt + Side button 1 |

### Recommended Bindings

**Best for minimal interference:**
- `mouse3` (middle click) - Won't interfere with normal browsing
- `mouse4` or `mouse5` (side buttons) - Dedicated buttons, very convenient
- `ctrl+mouse3` - Extra safety to avoid accidental triggers

**Avoid:**
- `mouse1` (left button) - Used for normal clicking
- `mouse2` (right button) - Used for context menus

---

## How to Set Mouse Bindings

### Method 1: GUI (Main Window)

1. Open the main window (double-click system tray icon)
2. Find the "Capture Hotkey" section in Settings
3. Enter your desired mouse binding (e.g., `mouse3` or `ctrl+mouse4`)
4. Click "Update Hotkey"
5. Test by showing the overlay and clicking the mouse button

### Method 2: Configuration File

Edit `ocr_settings.json`:

```json
{
  "capture_hotkey": "mouse3",
  "overlay_geometry": "300x50+100+100",
  "preprocessing_mode": "none"
}
```

Change `"capture_hotkey"` to your desired mouse binding.

**Restart the application** for changes to take effect.

---

## How It Works

### Pure Mouse Button

When you set a hotkey like `mouse3`:

1. Application registers a mouse listener for the middle button
2. When you click middle button anywhere on screen
3. OCR capture is triggered (if overlay is visible)

### Mouse + Keyboard Modifiers

When you set a hotkey like `ctrl+mouse3`:

1. Application registers a mouse listener for the middle button
2. When middle button is clicked, it checks if Ctrl is pressed
3. If Ctrl is pressed → trigger capture
4. If Ctrl is not pressed → ignore the click

This prevents accidental triggers from normal mouse usage.

---

## Troubleshooting

### Issue 1: "mouse module not available"

**Symptom:**
```
Warning: mouse module not available (No module named 'mouse').
Mouse button bindings will be disabled.
```

**Solution:**
```bash
# Install mouse module
pip install mouse

# If using virtual environment
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
pip install mouse
```

**Verify:**
```bash
python -c "import mouse; print('Mouse module OK')"
```

---

### Issue 2: Mouse binding not working

**Symptom:** You set `mouse3` as hotkey but nothing happens when you click middle button.

**Diagnostic Steps:**

1. **Check if mouse module is loaded:**
   - Look at startup messages
   - Should see: `[OK] Global hotkey registered: mouse(middle)`

2. **Check if overlay is visible:**
   - Mouse bindings ONLY work when overlay window is shown
   - Right-click tray → "Show Overlay" OR click "▶ Show Overlay" button

3. **Check hotkey is enabled:**
   - Look at overlay window's toggle button (停)
   - Should be RED (enabled)
   - If YELLOW, click it to enable

4. **Test with simple binding first:**
   - Try `mouse3` alone (no modifiers)
   - If that works, add modifiers: `ctrl+mouse3`

5. **Check permissions (Linux):**
   - Mouse library may need root permissions on Linux
   - Try running with sudo: `sudo python main.py`

---

### Issue 3: Mouse binding triggers even when modifiers aren't pressed

**Symptom:** Set `ctrl+mouse3` but it triggers even without Ctrl pressed.

**Cause:** Keyboard module may not be detecting modifiers correctly.

**Solutions:**
1. Ensure `keyboard` module is also installed: `pip install keyboard`
2. Check startup for keyboard availability
3. Try different modifiers: `alt+mouse3` or `shift+mouse3`

---

### Issue 4: Mouse binding conflicts with other software

**Symptom:** Mouse button doesn't work in other applications after setting binding.

**Cause:** Some mouse libraries can interfere with system mouse events.

**Solutions:**
1. **Use modifiers:** Instead of `mouse4`, use `ctrl+mouse4`
2. **Quit application when not needed:** This releases mouse hooks
3. **Change to different button:** Use less common buttons like `mouse5`

---

### Issue 5: Admin/Root required (Windows)

**Symptom:**
```
Warning: Could not register mouse hotkey: Access denied
```

**Cause:** Mouse library needs elevated permissions on some Windows versions.

**Solution:**
- Right-click Command Prompt or PowerShell
- Select "Run as Administrator"
- Run the application from elevated prompt

---

## Platform-Specific Notes

### Windows

✅ **Fully Supported**
- All mouse buttons work (mouse1-5)
- May require administrator privileges on some systems
- Best compatibility with Windows 10/11

### Linux

⚠️ **Requires Root**
- Mouse hooks require root permissions
- Run with: `sudo python main.py`
- Some desktop environments may have issues

### macOS

⚠️ **Limited Support**
- May require accessibility permissions
- Grant Python permission in System Preferences → Security & Privacy → Accessibility
- Some mouse buttons may not be recognized

---

## Best Practices

### Recommended Configurations

**For Gaming Mice (with side buttons):**
```
mouse4  # Side button 1 - very convenient, doesn't interfere
```

**For Standard Mice:**
```
mouse3  # Middle click - rarely used for other purposes
```

**For Extra Safety (prevent accidents):**
```
ctrl+mouse3  # Requires Ctrl held down
```

**For Workflows with japReader:**
```
mouse4  # Side button - can use while mouse is on text
```

### Tips

1. **Test before committing:** Try the binding with overlay visible first
2. **Avoid mouse1/mouse2:** These are essential for normal use
3. **Use modifiers in crowded environments:** Prevents accidental triggers
4. **Document your choice:** Remember which button you configured

---

## Advanced Usage

### Combining with Keyboard Hotkeys

You can have BOTH keyboard and mouse bindings, but only one is active at a time:

**Workflow:**
1. Use keyboard hotkey (`ctrl+shift`) when typing
2. Switch to mouse hotkey (`mouse4`) when browsing
3. Change via GUI Settings panel

### Multiple Modifiers

You can use multiple keyboard modifiers:

```
ctrl+alt+shift+mouse3  # All three modifiers + middle button
```

**Warning:** Complex combinations are harder to trigger accurately.

---

## Implementation Details

### How Mouse Bindings Work Internally

1. **Hotkey Parser:** `_parse_hotkey()` splits string into keyboard + mouse parts
2. **Mouse Listener:** `mouse.on_button()` registers callback for specific button
3. **Modifier Check:** When clicked, checks if keyboard modifiers are pressed
4. **Trigger:** If conditions met, calls `_on_hotkey_pressed()` → triggers capture

### Thread Safety

Mouse events occur on background thread. The implementation uses `root.after(0, callback)` to safely update the GUI from the mouse thread, preventing crashes.

### Resource Cleanup

When you change hotkeys or close the application:
- `mouse.unhook_all()` removes all mouse listeners
- Prevents hooks from persisting after app closes

---

## FAQ

**Q: Can I use both keyboard and mouse buttons together?**
A: Yes! For example, `ctrl+shift+mouse3` requires Ctrl+Shift held and middle click.

**Q: Does this work with trackpads?**
A: Trackpads usually don't have distinct buttons beyond left/right. Middle click and side buttons won't work.

**Q: Will this slow down my mouse?**
A: No. The listener is very lightweight and only checks clicks, not movements.

**Q: Can I bind scroll wheel?**
A: No. Only button clicks are supported (left, right, middle, side1, side2).

**Q: Does this work while the app is minimized?**
A: Mouse bindings only work when the **overlay window is visible**. The tray icon is separate.

**Q: Can I bind different mouse buttons to different actions?**
A: Currently, you can only set one hotkey at a time. All captures use the same binding.

---

## Validation

To verify mouse bindings are working correctly:

### Test Script

Run this simple test:

```python
import mouse

def on_click():
    print("Middle button clicked!")

mouse.on_button(on_click, buttons=('middle',), types=(mouse.UP,))
print("Click middle mouse button to test...")
mouse.wait()  # Wait forever
```

If this prints "Middle button clicked!" when you click, your mouse library is working.

---

## Related Documentation

- **[HOTKEY_CONFIGURATION.md](HOTKEY_CONFIGURATION.md)** - General hotkey configuration
- **[FEATURE_HOTKEY_CONFIG.md](FEATURE_HOTKEY_CONFIG.md)** - Technical implementation details
- **[WINDOWS_TESTING_GUIDE.md](WINDOWS_TESTING_GUIDE.md)** - Testing procedures

---

## Summary

✅ Mouse bindings are fully implemented and ready to use
✅ Supports mouse1-5 with or without keyboard modifiers
✅ Thread-safe implementation
✅ Works on Windows, Linux (root), macOS (with permissions)

**Recommended binding:** `mouse4` (side button) or `mouse3` (middle click)

**Quick Start:**
1. Ensure `mouse` module installed: `pip install mouse`
2. Set hotkey in GUI: `mouse3` or `ctrl+mouse4`
3. Show overlay and test!

---

*Implementation Date: 2025-11-29*
*Status: Fully Implemented and Tested*
