@echo off
setlocal

set "ROOT=%~dp0"
set "JAPREADER_DIR=%ROOT%study\japReader"
set "JAPREADER_EXE=%JAPREADER_DIR%\out\japreader-win32-x64\japreader.exe"

where npm >nul 2>&1
if errorlevel 1 (
    echo ERROR: npm was not found. Install Node.js before building japReader.
    exit /b 1
)

pushd "%JAPREADER_DIR%"
call npm ci
if errorlevel 1 goto :failed

call npm test
if errorlevel 1 goto :failed

call npm run lint
if errorlevel 1 goto :failed

call npm run package
if errorlevel 1 goto :failed
popd

if not exist "%JAPREADER_EXE%" (
    echo ERROR: japReader package was not created at:
    echo   %JAPREADER_EXE%
    exit /b 1
)

echo.
echo Local japReader package ready:
echo   %JAPREADER_EXE%
exit /b 0

:failed
set "RESULT=%ERRORLEVEL%"
popd
echo ERROR: Local japReader build failed.
exit /b %RESULT%
