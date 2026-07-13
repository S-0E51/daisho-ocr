@echo off
setlocal
set "PADDLE_MODE=cpu"
set "PADDLE_MODE_EXPLICIT="

if /I "%~1"=="gpu" ( set "PADDLE_MODE=gpu" & set "PADDLE_MODE_EXPLICIT=1" )
if /I "%~1"=="cpu" ( set "PADDLE_MODE=cpu" & set "PADDLE_MODE_EXPLICIT=1" )

REM With no explicit cpu/gpu argument, preserve an already-installed GPU (CUDA)
REM Paddle build instead of downgrading it to CPU on a plain re-run.
if not defined PADDLE_MODE_EXPLICIT if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" -c "import paddle,sys; sys.exit(0 if paddle.device.is_compiled_with_cuda() else 1)" >nul 2>&1
    if not errorlevel 1 (
        set "PADDLE_MODE=gpu"
        echo Detected an existing CUDA-enabled Paddle build; keeping GPU mode ^(pass "cpu" to override^).
    )
)

echo ==========================================
echo Daisho OCR v3.0 Setup
echo ==========================================
echo.
echo This setup installs:
echo   - PaddleOCR (PP-OCRv5) as the default engine
echo   - PaddleOCR-VL (0.9B) as the one-stop vision-language engine
echo   - manga-ocr as the stylized-text fallback
echo   - RapidOCR + ONNX Runtime as the fast CPU fallback
echo   - Surya OCR as the optional third engine
echo   - Paddle mode: %PADDLE_MODE%
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.10 or later from python.org
    pause
    exit /b 1
)

REM Create virtual environment if it doesn't exist
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment
        pause
        exit /b 1
    )
)

set "VENV_PYTHON=venv\Scripts\python.exe"
set "SITE_PACKAGES=venv\Lib\site-packages"
if not exist "%VENV_PYTHON%" (
    echo ERROR: Virtual environment Python not found at %VENV_PYTHON%
    pause
    exit /b 1
)

echo Using virtual environment Python:
echo   %VENV_PYTHON%
echo.

REM Upgrade packaging tools
echo Upgrading pip, wheel, and a torch-compatible setuptools...
"%VENV_PYTHON%" -m pip install --upgrade pip wheel "setuptools<82"
if errorlevel 1 (
    echo ERROR: Failed to upgrade pip tooling
    pause
    exit /b 1
)

REM Install requirements
echo Installing dependencies...
"%VENV_PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: Dependency installation failed.
    echo Check the pip output above for the package that caused the failure.
    pause
    exit /b 1
)

echo.
echo Preparing clean Paddle installation...
"%VENV_PYTHON%" -m pip uninstall -y paddlepaddle paddlepaddle-gpu >nul 2>&1
if exist "%SITE_PACKAGES%\paddle" rmdir /s /q "%SITE_PACKAGES%\paddle"
if exist "%SITE_PACKAGES%\paddlepaddle-3.2.0.dist-info" rmdir /s /q "%SITE_PACKAGES%\paddlepaddle-3.2.0.dist-info"
if exist "%SITE_PACKAGES%\paddlepaddle_gpu-3.2.0.dist-info" rmdir /s /q "%SITE_PACKAGES%\paddlepaddle_gpu-3.2.0.dist-info"
if exist "%SITE_PACKAGES%\~addle" rmdir /s /q "%SITE_PACKAGES%\~addle"
if exist "%SITE_PACKAGES%\~-ddle" rmdir /s /q "%SITE_PACKAGES%\~-ddle"
if exist "%SITE_PACKAGES%\paddle" (
    echo ERROR: Existing Paddle files could not be removed.
    echo Close the app if it is running and rerun setup.
    pause
    exit /b 1
)

echo.
if /I "%PADDLE_MODE%"=="gpu" (
    echo Switching Paddle to the NVIDIA GPU build...
    "%VENV_PYTHON%" -m pip install paddlepaddle-gpu==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu118/
    if errorlevel 1 (
        echo.
        echo WARNING: Failed to install the Paddle GPU wheel.
        echo Restoring the confirmed CPU build instead...
        "%VENV_PYTHON%" -m pip install paddlepaddle==3.2.0
        if errorlevel 1 (
            echo ERROR: Failed to restore the CPU Paddle build.
            pause
            exit /b 1
        )
        set "PADDLE_MODE=cpu"
    ) else (
        echo Verifying CUDA-enabled Paddle...
        "%VENV_PYTHON%" -c "import paddle, sys; has_device = hasattr(paddle, 'device'); compiled = has_device and paddle.device.is_compiled_with_cuda(); count = paddle.device.cuda.device_count() if compiled else 0; print('has_device=' + str(has_device)); print('compiled_with_cuda=' + str(compiled)); print('cuda_device_count=' + str(count)); sys.exit(0 if compiled else 1)"
        if errorlevel 1 (
            echo WARNING: Paddle installed, but CUDA was not detected in this environment.
            echo The app will continue to work, but OCR will run on CPU until CUDA is visible.
        )
    )
 ) else (
    echo Installing Paddle CPU build...
    "%VENV_PYTHON%" -m pip install paddlepaddle==3.2.0
    if errorlevel 1 (
        echo ERROR: Failed to install the CPU Paddle build.
        pause
        exit /b 1
    )
)
    echo.

echo.
echo Installing PaddleOCR-VL extras (paddlex[ocr])...
REM paddlex is already installed (via paddleocr) and satisfies this unpinned
REM requirement, so pip only adds the [ocr] extras without upgrading paddlex or Paddle.
"%VENV_PYTHON%" -m pip install "paddlex[ocr]"
if errorlevel 1 (
    echo WARNING: paddlex[ocr] extras failed to install.
    echo PaddleOCR-VL will be unavailable until you run:
    echo   "%VENV_PYTHON%" -m pip install "paddlex[ocr]"
)

echo.
echo Verifying key imports...
"%VENV_PYTHON%" -c "import os, importlib.util, sys; os.environ['DISABLE_MODEL_SOURCE_CHECK'] = 'True'; import paddle; mods=['PyQt6','PIL','manga_ocr','paddleocr','rapidocr','onnxruntime','surya']; missing=[m for m in mods if importlib.util.find_spec(m) is None]; paddle_ok = hasattr(paddle, 'device'); print('Missing modules: ' + ', '.join(missing) if missing else 'All key modules imported successfully.'); print('Paddle import OK: ' + str(paddle_ok)); sys.exit(1 if missing or not paddle_ok else 0)"
if errorlevel 1 (
    echo.
    echo ERROR: One or more key modules are still missing after installation.
    pause
    exit /b 1
)

echo.
where npm >nul 2>&1
if errorlevel 1 (
    echo WARNING: npm was not found, so the managed local japReader build was skipped.
    echo Install Node.js and run build_japreader.bat to enable direct integration.
) else (
    echo Building managed local japReader...
    call build_japreader.bat
    if errorlevel 1 (
        echo WARNING: japReader build failed. OCR setup will continue.
        echo Run build_japreader.bat later to retry.
    )
)

echo.
echo ==========================================
echo Setup complete!
echo ==========================================
echo.
echo To start the application, run: start.bat
echo.
echo Notes:
echo   - PP-OCRv5 is now the default engine for new installs
echo   - PaddleOCR-VL (0.9B) is installed too; select it in the tray or Settings
echo   - A plain re-run keeps an existing GPU Paddle build (pass "cpu" to force CPU)
echo   - Run setup.bat gpu to attempt the official Paddle GPU build
echo   - Or run setup_gpu.bat for the dedicated GPU setup shortcut
echo   - If the GPU wheel cannot be reached or CUDA is unavailable, setup falls back to CPU
echo   - First use of each engine may download model weights
echo   - Surya adds a larger optional OCR backend and may take longer on first load
echo.
pause
