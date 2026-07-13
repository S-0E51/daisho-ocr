#!/usr/bin/env python3
"""
Windows Compatibility Test Script
Tests all critical imports and features before running the full app
"""

import sys
import platform
import importlib.util

from _bootstrap import bootstrap


bootstrap()

print("=" * 70)
print("Windows Compatibility Test")
print("=" * 70)
print(f"Platform: {platform.system()} {platform.release()}")
print(f"Python: {sys.version}")
print()

# Test 1: Check stdout.buffer availability
print("[Test 1] Checking stdout.buffer...")
try:
    assert hasattr(sys.stdout, 'buffer'), "sys.stdout.buffer not available"
    print("  [OK] stdout.buffer available")
except AssertionError as e:
    print(f"  [FAIL] {e}")
    sys.exit(1)

# Test 2: Test UTF-8 encoding wrapper
print("[Test 2] Testing UTF-8 encoding wrapper...")
try:
    import io
    _utf8_stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
    _utf8_stdout.write("[OK] UTF-8 wrapper works\n")
    _utf8_stdout.flush()
except Exception as e:
    print(f"  [FAIL] {e}")
    sys.exit(1)

# Test 3: Test logging with UTF-8
print("[Test 3] Testing logging with UTF-8...")
try:
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)-8s | %(message)s',
        stream=_utf8_stdout
    )
    logger = logging.getLogger('Test')
    logger.info("[OK] Logging with UTF-8 works")
except Exception as e:
    print(f"  [FAIL] {e}")
    sys.exit(1)

# Test 4: Check required modules
print("[Test 4] Checking required modules...")
required_modules = [
    ('PyQt6', 'GUI framework'),
    ('PIL', 'Pillow image library'),
    ('numpy', 'Numerical array library'),
]

optional_modules = [
    ('pyperclip', 'Clipboard fallback'),
    ('pynput', 'Keyboard hotkeys'),
    ('mouse', 'Mouse side-button support'),
    ('dxcam', 'Preferred Windows capture backend'),
    ('manga_ocr', 'OCR engine'),
    ('paddleocr', 'PP-OCRv5 OCR engine'),
    ('transformers', 'Gemma vision verifier backend'),
    ('accelerate', 'Gemma model device mapping'),
    ('torchvision', 'Gemma image processor support'),
    ('rapidocr', 'RapidOCR ONNX engine'),
    ('surya', 'Surya OCR engine'),
]

missing_required = []
missing_optional = []

for module, description in required_modules:
    try:
        __import__(module)
        print(f"  [OK] {module:15s} - {description}")
    except ImportError:
        print(f"  [MISSING] {module:15s} - {description}")
        missing_required.append(module)

print()
print("[Test 5] Checking optional modules...")
for module, description in optional_modules:
    try:
        if importlib.util.find_spec(module) is None:
            raise ModuleNotFoundError(module)
        print(f"  [OK] {module:15s} - {description}")
    except ModuleNotFoundError:
        print(f"  [OPTIONAL] {module:15s} - {description}")
        missing_optional.append(module)

# Test 6: Test PyQt6 application and window creation
print()
print("[Test 6] Testing PyQt6 window creation...")
try:
    from PyQt6.QtWidgets import QApplication, QWidget

    app = QApplication.instance() or QApplication([])
    window = QWidget()
    window.setWindowTitle("Test Window")
    window.resize(200, 100)
    window.close()
    print("  [OK] PyQt6 window creation works")
except Exception as e:
    print(f"  [FAIL] {e}")
    sys.exit(1)

# Test 7: Check Qt system tray availability
print("[Test 7] Checking Qt system tray availability...")
try:
    from PyQt6.QtWidgets import QSystemTrayIcon
    if QSystemTrayIcon.isSystemTrayAvailable():
        print("  [OK] System tray available")
    else:
        print("  [INFO] System tray not available - app should fall back to visible window")
except Exception as e:
    print(f"  [FAIL] {e}")
    sys.exit(1)

# Test 8: Test PIL ImageGrab (Windows specific)
if platform.system() == 'Windows':
    print("[Test 8] Testing PIL ImageGrab on Windows...")
    try:
        from PIL import ImageGrab
        # Don't actually grab, just check if it's available
        print("  [OK] ImageGrab available")
    except Exception as e:
        print(f"  [FAIL] {e}")

# Summary
print()
print("=" * 70)
print("SUMMARY")
print("=" * 70)

if missing_required:
    print(f"[FAIL] Missing REQUIRED modules: {', '.join(missing_required)}")
    print("\nInstall with:")
    print(f"  pip install {' '.join(missing_required)}")
    sys.exit(1)
else:
    print("[OK] All required modules present")

if missing_optional:
    print(f"[INFO] Missing optional modules: {', '.join(missing_optional)}")
    print("       App will run with reduced functionality")
else:
    print("[OK] All optional modules present")

print()
print("[OK] Windows compatibility test PASSED")
print("      You can now run: python main.py")
print("=" * 70)
