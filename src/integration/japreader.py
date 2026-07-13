"""
japReader Integration - Auto-launch and window focus management.

Handles detecting japReader installation, launching it,
and bringing it to the foreground after OCR captures.
"""

from __future__ import annotations
import os
import subprocess
import time
from typing import Optional

from ..utils import BASE_DIR
from ..utils.logger import log_info, log_debug, log_warning, log_error

_PROCESS_CHECK_TTL_SEC = 3.0
_last_process_check = {"name": "", "running": False, "ts": 0.0}


def _is_process_running_native(process_name: str) -> Optional[bool]:
    """Check running processes using Win32 Toolhelp snapshot (no subprocess spawn)."""
    if os.name != "nt":
        return None

    try:
        import ctypes
        from ctypes import wintypes

        TH32CS_SNAPPROCESS = 0x00000002
        INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.Process32FirstW.restype = wintypes.BOOL
        kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.Process32NextW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == INVALID_HANDLE_VALUE:
            return None

        target = process_name.lower()
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)

        found = False
        try:
            has_entry = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while has_entry:
                if entry.szExeFile.lower() == target:
                    found = True
                    break
                has_entry = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)

        return found
    except Exception as e:
        log_debug(f"Native process check failed for {process_name}: {e}")
        return None


def get_japreader_search_paths() -> list[str]:
    """Get list of common japReader installation paths to check."""
    program_files = os.environ.get('PROGRAMFILES', 'C:\\Program Files')
    program_files_x86 = os.environ.get('PROGRAMFILES(X86)', 'C:\\Program Files (x86)')
    local_appdata = os.environ.get('LOCALAPPDATA', '')
    appdata = os.environ.get('APPDATA', '')
    user_home = os.path.expanduser('~')

    return [
        os.path.join(program_files, 'japReader', 'japReader.exe'),
        os.path.join(program_files_x86, 'japReader', 'japReader.exe'),
        os.path.join(local_appdata, 'japReader', 'japReader.exe'),
        os.path.join(appdata, 'japReader', 'japReader.exe'),
        os.path.join(user_home, 'japReader', 'japReader.exe'),
        os.path.join(local_appdata, 'Programs', 'japReader', 'japReader.exe'),
        os.path.join(user_home, 'Downloads', 'japReader', 'japReader.exe'),
        os.path.join(user_home, 'Desktop', 'japReader', 'japReader.exe'),
    ]


def get_local_japreader_search_paths() -> list[str]:
    """Return packaged local japReader candidates in priority order."""
    out_dir = os.path.join(BASE_DIR, "study", "japReader", "out")
    return [
        os.path.join(out_dir, "japreader-win32-x64", "japreader.exe"),
        os.path.join(out_dir, "japReader-win32-x64", "japReader.exe"),
        os.path.join(out_dir, "japreader-win32-x64", "japReader.exe"),
    ]


def detect_japreader(saved_path: str = "") -> Optional[str]:
    """Detect japReader installation. Returns path if found."""
    if saved_path and os.path.isfile(saved_path):
        log_debug(f"japReader found at saved path: {saved_path}")
        return saved_path

    for path in get_japreader_search_paths():
        if os.path.isfile(path):
            log_info(f"japReader auto-detected at: {path}")
            return path

    log_debug("japReader not found in common locations")
    return None


def detect_managed_japreader(saved_path: str = "") -> Optional[str]:
    """Prefer the project-local package, then a valid configured installation."""
    for path in get_local_japreader_search_paths():
        if os.path.isfile(path):
            log_info(f"Local managed japReader found at: {path}")
            return path
    return detect_japreader(saved_path)


def is_process_running(process_name: str) -> bool:
    """Check if a process with the given name is running (Windows)."""
    process_name = os.path.basename(process_name).lower()
    if not process_name:
        return False

    now = time.monotonic()
    if (
        _last_process_check["name"] == process_name
        and now - _last_process_check["ts"] < _PROCESS_CHECK_TTL_SEC
    ):
        return bool(_last_process_check["running"])

    running = _is_process_running_native(process_name)
    if running is not None:
        _last_process_check.update({"name": process_name, "running": running, "ts": now})
        return running

    try:
        run_kwargs = {}
        creation_flag = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if creation_flag:
            run_kwargs["creationflags"] = creation_flag

        result = subprocess.run(
            ['tasklist', '/FI', f'IMAGENAME eq {process_name}', '/NH'],
            capture_output=True, text=True,
            timeout=1.5,
            **run_kwargs,
        )
        running = process_name.lower() in result.stdout.lower()
        _last_process_check.update({"name": process_name, "running": running, "ts": now})
        return running
    except Exception as e:
        log_debug(f"Failed to check if {process_name} is running: {e}")
        return False


def launch_japreader(path: str) -> bool:
    """Launch japReader from the given path."""
    if not path or not os.path.isfile(path):
        log_debug("japReader path not found")
        return False

    exe_name = os.path.basename(path)
    if is_process_running(exe_name):
        log_info(f"japReader ({exe_name}) is already running, skipping launch")
        return True

    try:
        popen_kwargs = {"cwd": os.path.dirname(path)}
        detached = getattr(subprocess, "DETACHED_PROCESS", 0)
        new_group = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        creation_flags = detached | new_group
        if creation_flags:
            popen_kwargs["creationflags"] = creation_flags

        subprocess.Popen(
            [path],
            **popen_kwargs,
        )
        _last_process_check.update({"name": exe_name.lower(), "running": True, "ts": time.monotonic()})
        log_info(f"Launched japReader from: {path}")
        return True
    except Exception as e:
        log_error(f"Failed to launch japReader: {e}")
        return False


def focus_japreader() -> bool:
    """Bring japReader main window to the foreground (Windows only)."""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32

        EnumWindows = user32.EnumWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        GetWindowText = user32.GetWindowTextW
        GetWindowTextLength = user32.GetWindowTextLengthW
        IsWindowVisible = user32.IsWindowVisible
        SetForegroundWindow = user32.SetForegroundWindow
        ShowWindow = user32.ShowWindow
        BringWindowToTop = user32.BringWindowToTop
        GetForegroundWindow = user32.GetForegroundWindow
        GetWindowThreadProcessId = user32.GetWindowThreadProcessId
        AttachThreadInput = user32.AttachThreadInput
        GetCurrentThreadId = ctypes.windll.kernel32.GetCurrentThreadId
        IsIconic = user32.IsIconic
        SetWindowPos = user32.SetWindowPos

        SW_RESTORE = 9
        HWND_TOPMOST = -1
        HWND_NOTOPMOST = -2
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_SHOWWINDOW = 0x0040

        japreader_windows = []

        def enum_callback(hwnd, lParam):
            if IsWindowVisible(hwnd):
                length = GetWindowTextLength(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    GetWindowText(hwnd, buff, length + 1)
                    title = buff.value
                    if 'japreader' in title.lower():
                        japreader_windows.append((hwnd, title))
                        log_debug(f"Found japReader window: '{title}'")
            return True

        EnumWindows(EnumWindowsProc(enum_callback), 0)

        if not japreader_windows:
            log_debug("japReader window not found")
            return False

        # Find the main reader window (not dictionary, settings, etc.)
        main_hwnd = None
        skip_keywords = ['dictionary', 'dict', 'settings', 'config', 'about']

        for hwnd, title in japreader_windows:
            title_lower = title.lower()
            if any(skip in title_lower for skip in skip_keywords):
                continue
            if title_lower == 'japreader' or title_lower.startswith('japreader'):
                main_hwnd = hwnd
                log_debug(f"Selected main window: '{title}'")
                break

        if main_hwnd is None:
            for hwnd, title in japreader_windows:
                if not any(skip in title.lower() for skip in ['dictionary', 'dict']):
                    main_hwnd = hwnd
                    break

        if main_hwnd is None and japreader_windows:
            main_hwnd = japreader_windows[0][0]

        if main_hwnd:
            foreground_hwnd = GetForegroundWindow()
            if foreground_hwnd == main_hwnd:
                log_debug("japReader is already in foreground")
                return True

            if IsIconic(main_hwnd):
                ShowWindow(main_hwnd, SW_RESTORE)

            foreground_thread = GetWindowThreadProcessId(foreground_hwnd, None)
            current_thread = GetCurrentThreadId()

            attached = False
            if foreground_thread != current_thread:
                attached = AttachThreadInput(current_thread, foreground_thread, True)

            try:
                result = SetForegroundWindow(main_hwnd)

                if not result or GetForegroundWindow() != main_hwnd:
                    SetWindowPos(main_hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
                    SetWindowPos(main_hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)

                BringWindowToTop(main_hwnd)
                log_debug("japReader focus attempted")
                return True
            finally:
                if attached:
                    AttachThreadInput(current_thread, foreground_thread, False)

    except Exception as e:
        log_warning(f"Failed to focus japReader: {e}")
        return False
