# Startup Validation System

## Overview

The Japanese OCR Overlay Tool now includes an automatic startup validation system that checks package installation and available updates before the application launches.

## Features

### 1. Package Installation Validation

**Required Packages** (application will not start if missing):
- `manga-ocr` - Japanese OCR engine (core functionality)
- `Pillow` - Image processing library
- `pyperclip` - Clipboard integration
- `pystray` - System tray icon
- `keyboard` - Global hotkey support
- `mouse` - Mouse event handling
- `pygetwindow` - Window management

**Optional Packages** (features disabled if missing):
- `pytesseract` - Text detection for large text chunking (recommended)
- `opencv-python` - Fallback text detection for chunking

### 2. Update Checking

The validator checks PyPI for available package updates:
- Runs automatically on first launch
- Cached for 24 hours to avoid excessive network requests
- Shows which packages have updates available
- Displays current version → latest version

### 3. Auto-Installation (Optional)

The validator can automatically install missing required packages:
- Disabled by default (user must manually install)
- Can be enabled by editing `main.py` (see Configuration below)

## How It Works

### Startup Flow

```
┌─────────────────────────────────┐
│   User runs: python main.py     │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│  startup_validator.validate()   │
│  [1/3] Check required packages  │
│  [2/3] Check optional packages  │
│  [3/3] Check for updates (PyPI) │
└────────────┬────────────────────┘
             │
        ┌────┴────┐
        │         │
        ▼         ▼
    [PASS]    [FAIL]
        │         │
        │         ▼
        │    ┌──────────────────────┐
        │    │ Show error message   │
        │    │ Exit with code 1     │
        │    └──────────────────────┘
        │
        ▼
┌─────────────────────────────────┐
│  Continue application startup   │
│  Import heavy dependencies      │
│  Initialize OCR service         │
│  Launch GUI                     │
└─────────────────────────────────┘
```

### Example Output

```
======================================================================
Japanese OCR Overlay Tool - Startup Validation
======================================================================

[1/3] Checking required packages...
  [OK] manga-ocr            v0.1.10
  [OK] Pillow               v11.3.0
  [OK] pyperclip            v1.9.0
  [OK] pystray              v0.19.5
  [OK] keyboard             v0.13.5
  [OK] mouse                v0.7.1
  [OK] pygetwindow          v0.0.9

[2/3] Checking optional packages...
  [OK] pytesseract          v0.3.13
  [OK] opencv-python        v4.12.0.88

[3/3] Checking for updates...
  [^]  Pillow               Update available: 11.3.0 -> 12.0.0
  [^]  pyperclip            Update available: 1.9.0 -> 1.11.0
  [OK] manga-ocr            Up to date (0.1.10)
  [OK] pystray              Up to date (0.19.5)
  [OK] keyboard             Up to date (0.13.5)
  [OK] mouse                Up to date (0.7.1)
  [OK] pygetwindow          Up to date (0.0.9)
  [OK] pytesseract          Up to date (0.3.13)
  [OK] opencv-python        Up to date (4.12.0.88)

======================================================================
VALIDATION SUMMARY
======================================================================
Installed packages:       9/9
Missing (required):       0
Missing (optional):       0
Updates available:        2

Status: [OK] All packages installed

Updates available for:
  - Pillow: 11.3.0 -> 12.0.0
  - pyperclip: 1.9.0 -> 1.11.0

To update packages:
  pip install --upgrade manga-ocr Pillow pyperclip pystray keyboard mouse pygetwindow
======================================================================

[OK] Startup validation passed. Starting application...
```

## Configuration

### Enable/Disable Validation

Edit [main.py](main.py) lines 16-37:

```python
# To disable validation entirely, comment out this block:
if __name__ == '__main__':
    try:
        from startup_validator import validate_startup
        validation_passed = validate_startup(auto_install=False, check_updates=True)
        # ... rest of validation code
```

### Enable Auto-Installation

Change `auto_install=False` to `auto_install=True` in [main.py:22](main.py#L22):

```python
# Before (manual installation required)
validation_passed = validate_startup(auto_install=False, check_updates=True)

# After (automatic installation)
validation_passed = validate_startup(auto_install=True, check_updates=True)
```

**Warning:** Auto-installation requires write permissions and may take several minutes on first run.

### Disable Update Checking

Change `check_updates=True` to `check_updates=False` in [main.py:22](main.py#L22):

```python
# Disable update checking (faster startup, no network access)
validation_passed = validate_startup(auto_install=False, check_updates=False)
```

## Standalone Usage

You can run the validator independently:

```bash
# Basic validation
python startup_validator.py

# With auto-installation
python startup_validator.py --auto-install

# Skip update checking
python startup_validator.py --no-update-check
```

### Command-Line Options

| Option | Description |
|--------|-------------|
| `--auto-install` | Automatically install missing required packages |
| `--no-update-check` | Skip checking PyPI for updates (faster) |

### Exit Codes

- `0` - Validation passed (all required packages installed)
- `1` - Validation failed (missing required packages)

## Update Check Caching

Update checks are cached to avoid excessive network requests:

- **Cache file:** `update_check_cache.json`
- **Cache duration:** 24 hours
- **Cache location:** Same directory as application

### Cache File Format

```json
{
  "last_check": "2025-11-29T16:30:45.123456",
  "packages": {
    "manga-ocr": {
      "current_version": "0.1.10",
      "latest_version": "0.1.10"
    },
    "Pillow": {
      "current_version": "11.3.0",
      "latest_version": "12.0.0"
    }
  }
}
```

To force an update check, delete this file.

## Troubleshooting

### Validation Takes Too Long

**Cause:** Network timeout when checking PyPI for updates

**Solutions:**
1. Disable update checking: `check_updates=False`
2. Check internet connection
3. Delete `update_check_cache.json` to reset cache

### False Negatives (Package Installed But Shows Missing)

**Cause:** Package name mismatch between PyPI and import name

**Example:** `opencv-python` (PyPI) vs `cv2` (import)

**Solution:** The validator tries multiple name variations automatically. If issues persist, check package installation:
```bash
pip list | grep package-name
```

### Auto-Install Fails

**Common issues:**
1. **No write permissions:** Run with elevated privileges or install manually
2. **Network error:** Check internet connection
3. **Package conflicts:** Resolve conflicts manually with pip

**Recommended approach:** Use manual installation:
```bash
pip install -r requirements.txt
```

### Startup Validator Not Found

**Error:**
```
Note: Startup validator not found, skipping validation checks.
```

**Cause:** `startup_validator.py` not in the same directory as `main.py`

**Solution:** Ensure both files are in the same directory

### Import Errors After Validation Passes

**Cause:** Package installed but import name different

**Example:**
- Package: `opencv-python`
- Import: `import cv2`

**Solution:** Validation only checks package installation, not import names. Ensure you're importing correctly.

## Performance Impact

### Startup Time

| Configuration | First Run | Subsequent Runs |
|--------------|-----------|-----------------|
| No validation | 0ms | 0ms |
| Validation (no update check) | ~100ms | ~100ms |
| Validation (with update check) | ~2-5s | ~100ms (cached) |
| Validation (with auto-install) | ~30-120s | ~100ms |

**Recommendation:** Use default settings (validation enabled, update check enabled) for best balance of safety and performance.

### Network Usage

- **Package check:** No network (local only)
- **Update check:** ~5-10 KB per package (PyPI JSON API)
- **Total:** ~50-100 KB per update check
- **Frequency:** Once per 24 hours (cached)

## Security Considerations

### Network Access

The validator makes HTTPS requests to:
- `https://pypi.org/pypi/{package_name}/json` (update checking)

No other network access is performed. No user data is transmitted.

### Auto-Installation

When `auto_install=True`, the validator runs:
```bash
python -m pip install {package_name}
```

This downloads packages from PyPI. Only enable if you trust the package sources.

### Recommendations

1. **Keep auto_install=False** (default) for security
2. **Review requirements.txt** before manual installation
3. **Check update_check_cache.json** to see what versions are available
4. **Use virtual environment** to isolate dependencies

## Files

| File | Purpose |
|------|---------|
| [startup_validator.py](startup_validator.py) | Validation module (433 lines) |
| [main.py](main.py) | Integration (lines 10-37) |
| `update_check_cache.json` | Update check cache (auto-generated) |

## API Reference

### StartupValidator Class

```python
from startup_validator import StartupValidator

validator = StartupValidator(auto_install=False, check_updates=True)
success = validator.validate()

# Get missing packages
missing = validator.get_missing_required()

# Get available updates
updates = validator.get_update_available()  # [(name, current, latest), ...]
```

### Convenience Function

```python
from startup_validator import validate_startup

# Quick validation
success = validate_startup(auto_install=False, check_updates=True)
```

## Future Enhancements

Potential improvements for future versions:

- [ ] GUI progress dialog during validation
- [ ] Configurable update check interval
- [ ] Version pinning support (requirements.txt parsing)
- [ ] Rollback support for failed updates
- [ ] Offline mode detection (skip update check automatically)
- [ ] Detailed logging of validation results

## Related Documentation

- [WINDOWS_TESTING_GUIDE.md](WINDOWS_TESTING_GUIDE.md) - Testing procedures
- [requirements.txt](requirements.txt) - Package dependencies
- [DEPLOYMENT_SUMMARY.md](DEPLOYMENT_SUMMARY.md) - Deployment details

---

**Status:** ✅ Implemented and integrated
**Version:** 1.0
**Last Updated:** 2025-11-29
