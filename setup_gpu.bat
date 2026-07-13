@echo off
setlocal

call "%~dp0setup.bat" gpu
exit /b %errorlevel%
