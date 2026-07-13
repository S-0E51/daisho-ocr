# Windows Testing Guide - Large Text Chunking Feature

## Quick Start

This guide helps you test the newly integrated Large Text Chunking feature on Windows.

## Prerequisites

- Windows 10/11 (native, not WSL)
- Python 3.8+ installed
- Virtual environment already set up

## Installation Steps

### 1. Install Python Dependencies

Open Command Prompt or PowerShell in the project directory:

```cmd
venv\Scripts\activate
pip install pytesseract opencv-python
```

**Expected output:**
```
Successfully installed pytesseract-0.3.13 opencv-python-4.x.x numpy-2.x.x
```

### 2. Install Tesseract Binary (Recommended)

**Option A: Download Installer**
1. Visit [UB-Mannheim Tesseract](https://github.com/UB-Mannheim/tesseract/wiki)
2. Download the latest Windows installer (e.g., `tesseract-ocr-w64-setup-5.3.x.exe`)
3. Run installer - **IMPORTANT:** Note the installation path (default: `C:\Program Files\Tesseract-OCR`)
4. During installation, make sure "Add to PATH" is checked

**Option B: Using Chocolatey**
```cmd
choco install tesseract
```

**Verify Installation:**
```cmd
tesseract --version
```

Expected output:
```
tesseract 5.x.x
```

If command not found, add to PATH manually:
1. Search for "Environment Variables" in Windows
2. Edit "Path" under System Variables
3. Add: `C:\Program Files\Tesseract-OCR`
4. Restart Command Prompt

### 3. Configure Tesseract Path (If Needed)

If Tesseract is installed but pytesseract can't find it, you may need to set the path in Python:

Create a file named `tesseract_config.py` in the project directory:

```python
import pytesseract

# Set tesseract path (adjust if installed elsewhere)
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
```

Then import this at the top of `main.py` (optional, only if auto-detection fails).

## Testing Checklist

### Phase 1: Test Without Tesseract (Fallback Mode)

**Purpose:** Verify app works gracefully without Tesseract

1. **Rename Tesseract temporarily** (or skip installation)
2. **Run the app:**
   ```cmd
   python main.py
   ```
3. **Check system tray** - App should minimize to tray
4. **Open main window** - Double-click tray icon or right-click → "Show Main Window"
5. **Find "🧩 Large Text Chunking" card**
   - Should show status: "OpenCV ✓" (yellow) or "Not Available" (gray)
   - If OpenCV available: Controls enabled but detection limited
   - If not available: All controls grayed out
6. **Test OCR on small text** - Should work normally (original behavior)

**Expected Results:**
- ✅ App starts without errors
- ✅ Chunking card visible but may show limited availability
- ✅ OCR still functional for basic use
- ⚠️ Chunking may not work optimally without Tesseract

### Phase 2: Test With Tesseract (Full Features)

**Purpose:** Test complete chunking functionality

1. **Install Tesseract** (see Installation Steps above)
2. **Restart the app**
3. **Check chunking status:**
   - Should show "Tesseract ✓" (green)
   - All controls enabled

4. **Test Default Settings (Auto Mode):**
   - Enable checkbox: ✅ Checked
   - Mode: 🔘 Auto
   - Reading: 🔘 Manga (RTL)

5. **Capture Small Text (e.g., single speech bubble):**
   - Show overlay (right-click tray → "Show Overlay")
   - Position over small text region
   - Press `Ctrl+Shift` to capture
   - **Expected:** Fast processing (~200-300ms), direct OCR used
   - **Check logs:** Should say "Auto mode: Using direct processing"

6. **Capture Large Text (e.g., full manga page):**
   - Position overlay over large text area
   - Press `Ctrl+Shift` to capture
   - **Expected:** Slower processing (~1-2s), chunking used
   - **Check logs:** Should say "Auto mode: Using chunked processing"
   - **Check logs:** Should show chunk count and processing time

### Phase 3: Test Chunking Modes

**Test "Always" Mode:**
1. Change mode to: 🔘 Always
2. Capture small text
3. **Expected:** Even small text uses chunking (slower but still accurate)
4. **Check logs:** Should show chunking applied

**Test "Never" Mode:**
1. Change mode to: 🔘 Never
2. Capture large text
3. **Expected:** Direct processing only (faster but may be less accurate)
4. **Check logs:** No chunking messages

### Phase 4: Test Reading Orders

**Manga (RTL) - Default:**
1. Set reading order to: 🔘 Manga (RTL)
2. Capture vertical Japanese manga page with multiple text blocks
3. **Expected:** Text read top-to-bottom, then right-to-left
4. Verify text order makes sense in Japanese reading flow

**Manhwa (LTR):**
1. Set reading order to: 🔘 Manhwa (LTR)
2. Capture Korean manhwa or horizontal Japanese text
3. **Expected:** Text read top-to-bottom, then left-to-right

**Western:**
1. Set reading order to: 🔘 Western
2. Capture English/Western comic
3. **Expected:** Text read left-to-right, then top-to-bottom

### Phase 5: Test Settings Persistence

1. **Change all settings:**
   - Disable chunking
   - Change mode to "Always"
   - Change reading to "Western"
2. **Close app completely** (Quit from tray)
3. **Restart app**
4. **Check settings:**
   - Should retain all changed settings
   - Verify `ocr_settings.json` contains chunking settings

### Phase 6: Performance Comparison

**Create Test Images:**
- Small: Single speech bubble (~10-30 characters)
- Medium: 2-3 speech bubbles (~50-100 characters)
- Large: Full manga page (~200-500 characters)

**Test Each with Different Modes:**

| Image Size | Mode | Expected Time | Expected Accuracy |
|------------|------|---------------|-------------------|
| Small | Auto | ~200ms | High (direct) |
| Small | Always | ~500ms | High (chunked) |
| Medium | Auto | ~400ms | High (direct or chunked) |
| Medium | Always | ~800ms | High (chunked) |
| Large | Auto | ~1500ms | High (chunked) |
| Large | Never | ~800ms | Medium-Low (may fail) |

**Record your results in a table:**

```
Test Results:
-------------
[Image Type] | [Mode] | [Time] | [Accuracy] | [Notes]
Small bubble | Auto   | ___ms  | Good/Bad   | ___________
Small bubble | Always | ___ms  | Good/Bad   | ___________
Large page   | Auto   | ___ms  | Good/Bad   | ___________
Large page   | Never  | ___ms  | Good/Bad   | ___________
```

## Troubleshooting

### Tesseract Not Detected

**Symptom:** Status shows "OpenCV ✓" or "Not Available" even after installing Tesseract

**Solutions:**
1. Verify Tesseract is in PATH:
   ```cmd
   tesseract --version
   ```
2. If not found, add to PATH (see Installation Steps)
3. Restart Command Prompt/PowerShell AND the app
4. Check pytesseract can find it:
   ```python
   python -c "import pytesseract; print(pytesseract.get_tesseract_version())"
   ```

### Chunking Makes Results Worse

**Symptom:** Chunking produces incorrect or garbled text

**Possible Causes:**
- Wrong reading order for content type
- Text too dense (chunks too small)
- Better suited for direct processing

**Solutions:**
1. Try different reading orders
2. Use "Never" mode for that specific content
3. Reduce capture area to isolate specific text
4. Combine with different preprocessing modes

### Slow Performance

**Symptom:** Chunking is very slow (>3 seconds)

**Normal for:**
- Very large images (>1000x1000 pixels)
- Dense text with many chunks
- First run (model loading)

**Abnormal causes:**
- System resources low
- Too many chunks created
- Tesseract detection slow

**Solutions:**
1. Use "Auto" mode instead of "Always"
2. Reduce capture area
3. Use "Never" mode for quick captures
4. Check system resources (CPU, RAM)

### App Crashes on Startup

**Check log file:** `ocr_overlay.log`

**Common issues:**
1. Missing core dependencies: `pip install -r requirements.txt`
2. Corrupt settings: Delete `ocr_settings.json` and restart
3. Import errors: Check log for specific missing module

## Verification Summary

After testing, confirm:

- ✅ App starts successfully with Tesseract installed
- ✅ Chunking card shows "Tesseract ✓" status
- ✅ Small text uses direct processing (Auto mode)
- ✅ Large text uses chunking (Auto mode)
- ✅ Always mode forces chunking on all images
- ✅ Never mode disables chunking
- ✅ All three reading orders produce sensible results
- ✅ Settings persist across restarts
- ✅ Performance is acceptable (<2s for large images)
- ✅ No regression on small text accuracy

## Reporting Issues

If you find problems during testing, please document:

1. **What you were doing** (which test, which settings)
2. **What you expected** (based on this guide)
3. **What actually happened** (error message, wrong output, etc.)
4. **Log file snippet** (`ocr_overlay.log`)
5. **System info** (Windows version, Python version, Tesseract version)

## Next Steps

After successful testing:

1. ✅ Integration is complete and working
2. Consider creating sample test images for future testing
3. Experiment with real-world use cases
4. Fine-tune chunk size if needed (currently 384px default)
5. Share feedback on accuracy improvements

---

**Happy Testing!** 🎉

The chunking feature should significantly improve OCR accuracy on large text blocks while maintaining excellent performance on small captures.
