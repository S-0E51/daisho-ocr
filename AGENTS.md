# Repository Guidelines

## Project Structure & Module Organization
- `main.py` is the entrypoint for the PyQt6 desktop application.
- `src/` contains production code grouped by domain:
- `src/ui/` for main window, tray, settings dialog, theme, and hotkeys.
- `src/capture/` for the transparent overlay capture window.
- `src/ocr/` for OCR engine management (`manga_ocr`, `paddle_ocr`) and cache logic.
- `src/processing/` for image preprocessing.
- `src/integration/` for clipboard and external app integration.
- `src/utils/` for shared utilities (for example logging and base paths).
- `tests/` contains script-based smoke/manual validation scripts.
- `assets/` stores tray/app icons; `docs/` stores design and implementation notes.
- Treat `venv/`, `versions/`, and `backups/` as local artifacts, not active source folders.

## Build, Test, and Development Commands
- `python -m venv venv && source venv/bin/activate` (`venv\Scripts\activate` on Windows): create and activate a virtual environment.
- `pip install -r requirements.txt`: install dependencies.
- `python main.py`: run the app in the foreground.
- `setup.bat`: Windows setup helper (creates venv, installs requirements).
- `start.bat`: Windows launcher (uses `pythonw` when available).
- `python tests/test_windows.py`: platform/dependency smoke test.
- `python tests/test_manga_ocr.py`: verify `manga-ocr` import and inference.
- `python tests/simple_overlay_test.py`: manual overlay interaction check.

## Coding Style & Naming Conventions
- Follow existing Python conventions: 4-space indentation, PEP 8 spacing, concise docstrings.
- Use `snake_case` for functions/variables/modules and `PascalCase` for classes.
- Keep type hints on public methods and manager APIs, matching current `src/` patterns.
- Prefer adding logic in focused `src/*` modules instead of expanding `main.py`.

## Testing Guidelines
- The repository currently uses executable test scripts rather than a `pytest` suite.
- Name new tests `tests/test_<feature>.py` and keep them runnable via `python <file>`.
- For OCR or capture changes, validate both startup and end-to-end capture-to-clipboard flow.

## Commit & Pull Request Guidelines
- This workspace snapshot does not include `.git` history, so project-specific commit patterns cannot be derived here.
- Use Conventional Commit prefixes (`feat:`, `fix:`, `refactor:`, `docs:`) in imperative mood.
- PRs should include: objective, touched paths (for example `src/ocr/manager.py`), test commands run, and screenshots/GIFs for UI changes.
