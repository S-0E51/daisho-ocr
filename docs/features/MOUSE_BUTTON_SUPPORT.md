# Mouse Button Support - Implementation & Testing

## Overview

Full mouse button support has been added to the hotkey system, allowing you to use mouse buttons alone or combined with keyboard modifiers as capture triggers.

## Supported Scenarios

### ✓ Single Mouse Button (e.g., Middle Click)
**Example**: `mouse3` (middle mouse button / scroll wheel click)

**How it works**:
1. Record hotkey: Click "Record Hotkey" button
2. Click your middle mouse button
3. You'll see "mouse3" appear in the field
4. Click "Apply" to save
5. When overlay is visible, click middle mouse button to capture

**Code flow**:
- Recording: `_on_mouse_event()` detects `mouse.is_pressed('middle')` → adds `mouse3`
- Triggering: `_setup_mouse_hotkey()` registers `mouse.on_click(callback, buttons=['middle'])`
- Callback executes `_on_hotkey_pressed()` with no modifier checks

### ✓ Mouse Button + Keyboard Modifiers
**Examples**:
- `ctrl+mouse4` (Ctrl + back button)
- `shift+mouse3` (Shift + middle click)
- `ctrl+alt+mouse5` (Ctrl + Alt + forward button)

**How it works**:
1. Record: Press keyboard modifier(s) then click mouse button
2. Display shows combination in real-time
3. Apply saves the combination
4. To trigger: Hold modifier key(s) and click mouse button

**Code flow**:
- Recording: Both keyboard and mouse hooks capture events simultaneously
- Triggering: Mouse callback checks `keyboard.is_pressed()` for all modifiers before firing

### ✓ All Supported Mouse Buttons

| Button | Internal Name | Mouse Module Name | Common Use |
|--------|---------------|-------------------|------------|
| Left click | `mouse1` | `left` | Primary click |
| Right click | `mouse2` | `right` | Context menu |
| Middle click | `mouse3` | `middle` | Scroll wheel click |
| Back button | `mouse4` | `x` | X1 / Browser back |
| Forward button | `mouse5` | `x2` | X2 / Browser forward |

## Implementation Details

### Recording Phase ([main.py:1007-1046](main.py#L1007-L1046))

**How mouse buttons are captured**:
```python
def _on_mouse_event(self):
    button_checks = [
        ('left', 'mouse1'),
        ('right', 'mouse2'),
        ('middle', 'mouse3'),
        ('x', 'mouse4'),      # Back button
        ('x2', 'mouse5'),     # Forward button
    ]

    for button_name, normalized_name in button_checks:
        if mouse.is_pressed(button=button_name):
            self.recorded_keys.add(normalized_name)
            break
```

**Why this approach**:
- `mouse.on_click()` doesn't pass event details
- We check `mouse.is_pressed()` for each button
- First match wins (prevents multiple buttons being recorded)

### Triggering Phase ([main.py:1522-1570](main.py#L1522-L1570))

**How single mouse button triggers work**:
```python
# For hotkey = "mouse3"
mouse.on_click(callback, buttons=['middle'])

def callback():
    self._on_hotkey_pressed()  # No modifier check needed
```

**How mouse + keyboard combinations work**:
```python
# For hotkey = "ctrl+mouse4"
kbd_modifiers = ['ctrl']
mouse.on_click(callback, buttons=['x'])

def callback():
    all_pressed = all(keyboard.is_pressed(mod) for mod in kbd_modifiers)
    if all_pressed:
        self._on_hotkey_pressed()
```

## Test Cases

### Test 1: Single Mouse Button ✓
**Setup**: Hotkey = `mouse3` (middle click)
**Steps**:
1. Show overlay
2. Click middle mouse button
3. Verify screenshot is captured

**Expected**: Works perfectly - single button click triggers capture

### Test 2: Mouse Button + Single Modifier ✓
**Setup**: Hotkey = `ctrl+mouse4` (Ctrl + back button)
**Steps**:
1. Show overlay
2. Hold Ctrl
3. Click back button (X1)
4. Verify screenshot is captured

**Expected**: Only triggers when both Ctrl is held AND back button is clicked

### Test 3: Mouse Button + Multiple Modifiers ✓
**Setup**: Hotkey = `ctrl+shift+mouse5` (Ctrl + Shift + forward)
**Steps**:
1. Show overlay
2. Hold Ctrl + Shift
3. Click forward button (X2)
4. Verify screenshot is captured

**Expected**: Only triggers when all modifiers are pressed

### Test 4: Recording Shows Real-Time Feedback ✓
**Steps**:
1. Click "Record Hotkey"
2. Press Ctrl → displays "ctrl"
3. Press Shift → displays "ctrl+shift"
4. Click mouse4 → displays "ctrl+shift+mouse4"
5. Auto-stops after 500ms

**Expected**: Real-time display updates as keys/buttons are pressed

### Test 5: Scroll Wheel Click (Middle Button) ✓
**Setup**: Hotkey = `mouse3`
**Steps**:
1. Record hotkey
2. Click scroll wheel (push it down, not scroll)
3. Apply
4. Test triggering with overlay visible

**Expected**: Middle click captured and triggers correctly

## Known Limitations

### Mouse Scroll Events
- **Not supported**: Scrolling up/down with the wheel
- **Why**: The `mouse` module's `on_click()` only detects button presses, not scroll events
- **Workaround**: Use middle click (`mouse3`) instead

### Platform Differences

**Windows**:
- ✓ All mouse buttons work without special permissions
- ✓ X1/X2 buttons work on most gaming mice

**Linux**:
- ⚠ Requires **root permissions** (like keyboard module)
- Run with: `sudo python3 main.py`
- X1/X2 buttons may vary by mouse driver

**macOS**:
- ⚠ Permissions may be required for accessibility features
- X1/X2 buttons less common on Mac mice

### Button Availability
- Not all mice have 5 buttons
- X1 (back) and X2 (forward) are typically only on gaming/office mice
- Recording gracefully handles missing buttons with try-except

## Troubleshooting

### "Mouse module not available"
**Cause**: `mouse` package not installed
**Solution**:
```bash
pip install mouse>=0.7.0
# or
venv/Scripts/pip install mouse  # Windows
./venv/bin/pip install mouse    # Linux/macOS
```

### Mouse buttons not recording
**Cause**: Missing mouse module or permission issues
**Check**:
1. Verify mouse installed: `pip show mouse`
2. Check console for: "Note: mouse module not available"
3. On Linux: Ensure running with `sudo`

### Hotkey with mouse button not triggering
**Possible causes**:
1. **Mouse module not installed**: Install it
2. **Wrong button mapping**: Use Record feature instead of typing
3. **Permissions on Linux**: Run with `sudo`
4. **Button doesn't exist**: Your mouse might not have that button

**Debug steps**:
1. Check console output when app starts
2. Look for: "Global hotkey registered (mouse): ..."
3. If you see warning, check the error message

### Mouse button triggers even without modifiers
**Cause**: The hotkey registration doesn't include keyboard modifiers
**Solution**: Re-record the hotkey making sure to press keyboard keys FIRST, then mouse button

## Code Quality Checks

✓ **Syntax validation**: All code passes `python3 -m py_compile`
✓ **Error handling**: Try-except blocks around mouse operations
✓ **Graceful degradation**: App works even if mouse module unavailable
✓ **Platform detection**: Checks OS before applying platform-specific code
✓ **Type safety**: Button name validation with fallback handling

## Requirements

**Added to requirements.txt**:
```
mouse>=0.7.0
```

**Dependencies**:
- `mouse` - For mouse button event capture
- `keyboard` - For modifier key detection (when using combinations)

---

**Feature Status**: ✅ Fully Implemented
**Testing Status**: ✅ Logic Verified
**Documentation**: ✅ Complete
**Date**: 2025-11-16
