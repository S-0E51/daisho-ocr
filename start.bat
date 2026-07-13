@echo off
echo Starting MangaReader-OCR...

REM Use pythonw from virtual environment (no console window)
if exist "venv\Scripts\pythonw.exe" (
    start "" venv\Scripts\pythonw.exe main.py
    exit /b 0
)

REM If venv doesn't exist, try to auto-detect Python
echo Virtual environment not found. Attempting to locate Python...

set PYTHON_CMD=

REM Check if pythonw is in PATH
where pythonw >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set PYTHON_CMD=pythonw
    echo Found Python in PATH
    goto :run_app
)

REM Check common installation directories
for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\pythonw.exe"
    "C:\Python313\pythonw.exe"
    "C:\Python312\pythonw.exe"
    "C:\Python311\pythonw.exe"
    "C:\Python310\pythonw.exe"
) do (
    if exist %%P (
        set PYTHON_CMD=%%P
        echo Found Python at %%P
        goto :run_app
    )
)

REM Python not found
echo ERROR: Python not found!
echo Please either:
echo   1. Run setup.bat to create virtual environment, OR
echo   2. Install Python from https://www.python.org/downloads/
pause
exit /b 1

:run_app
REM Run the application
if defined PYTHON_CMD (
    start "" %PYTHON_CMD% main.py
) else (
    start "" pythonw main.py
)

REM Keep console open if there was an error
if errorlevel 1 (
    echo.
    echo Application exited with error.
    pause
)
