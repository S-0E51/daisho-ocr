# Tests

This project uses executable smoke-test scripts instead of a pytest suite. Run
them from the repository root with the project virtual environment activated.

## Fast Checks

```bash
python -m compileall -q main.py src tests
python tests\test_windows.py
python tests\test_capture_visibility.py
python tests\test_japreader_integration.py
python tests\test_japreader_companion_ui.py
python tests\test_overlay_to_mouse_hold.py
python tests\test_ocr_cache.py
python tests\test_paddle_profile_loading.py
python tests\test_text_correction.py
python tests\test_vision_verifier.py
python tests\test_ocr_comparison.py
python tests\test_manga_ocr.py
python tests\test_manga_ocr_only.py
python tests\test_surya_analysis.py
python tests\test_rapid_ocr.py
```

## Test Files

- `test_windows.py`: Windows, dependency, PyQt6, tray, and screenshot smoke checks.
- `test_capture_visibility.py`: capture hotkey/manual capture checks while the overlay is hidden.
- `test_japreader_integration.py`: local bridge contract, delivery queue, fallback, and managed companion behavior.
- `test_japreader_companion_ui.py`: japReader status controls and legacy settings migration without loading OCR models.
- `test_overlay_to_mouse_hold.py`: tap-vs-hold checks for the overlay-to-mouse hotkey.
- `test_ocr_cache.py`: exact image cache keys and optional-stage cacheability checks.
- `test_paddle_profile_loading.py`: Paddle profile switching while a model load is in flight.
- `test_text_correction.py`: conservative Japanese post-OCR correction checks.
- `test_vision_verifier.py`: Gemma visual verification parsing and decision checks without loading a model.
- `test_ocr_comparison.py`: secondary-engine comparison heuristics.
- `test_manga_ocr.py`: active manga-ocr wrapper integration without model download by default.
- `test_manga_ocr_only.py`: legacy command shim that now validates the multi-engine OCR manager.
- `test_surya_analysis.py`: Surya result parsing and confidence extraction without model weights.
- `test_rapid_ocr.py`: optional RapidOCR output normalization without model weights.
- `simple_overlay_test.py`: manual interactive check for the real PyQt overlay.

## Heavy Model Checks

Some OCR model tests may download weights or require local model caches. Run
them explicitly when you want full inference validation:

```bash
python tests\test_manga_ocr.py --load-model
```

The same behavior can be enabled with:

```bash
set DAISHO_TEST_LOAD_MODELS=1
python tests\test_manga_ocr.py
```

## Console Encoding

Shared test bootstrap code configures UTF-8 output with replacement handling so
the scripts run in the default Windows console as well as UTF-8 terminals.

## Adding Tests

New tests should be named `tests/test_<feature>.py`, remain runnable with
`python tests\<file>.py`, and avoid model downloads unless the user explicitly
opts in through a flag or environment variable.
