"""Read and activate windows owned by one exact client executable."""

import ctypes
from ctypes import wintypes
import os
import time


def windows_for(executable):
    if os.name != 'nt':
        raise RuntimeError('Window control requires Windows')
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    expected_path = os.path.normcase(str(executable.resolve()))
    windows = []

    def visit(window, _):
        if not user32.IsWindowVisible(window):
            return True
        text_length = user32.GetWindowTextLengthW(window)
        if not text_length:
            return True
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, ctypes.byref(process_id))
        process = kernel32.OpenProcess(0x1000, False, process_id.value)
        if not process:
            return True
        try:
            path_buffer = ctypes.create_unicode_buffer(32768)
            capacity = wintypes.DWORD(len(path_buffer))
            if not kernel32.QueryFullProcessImageNameW(process, 0, path_buffer, ctypes.byref(capacity)):
                return True
            if os.path.normcase(path_buffer.value) != expected_path:
                return True
            title = ctypes.create_unicode_buffer(text_length + 1)
            user32.GetWindowTextW(window, title, len(title))
            windows.append({'pid': process_id.value, 'window': int(window), 'title': title.value})
        finally:
            kernel32.CloseHandle(process)
        return True

    if not user32.EnumWindows(callback_type(visit), 0):
        raise ctypes.WinError(ctypes.get_last_error())
    user32.GetForegroundWindow.restype = wintypes.HWND
    return user32, windows


def window_status(executable):
    user32, windows = windows_for(executable)
    foreground = int(user32.GetForegroundWindow() or 0)
    for window in windows:
        window['foreground'] = window['window'] == foreground
    return {'ok': True, 'app': str(executable.resolve()), 'windows': windows,
            'business_requests_sent': 0}


def window_focus(executable, handle=None):
    user32, windows = windows_for(executable)
    candidates = [window for window in windows if handle is None or window['window'] == handle]
    if len(candidates) != 1:
        return {'ok': False, 'error': 'Select exactly one existing window with --window',
                'windows': candidates, 'business_requests_sent': 0}
    selected = candidates[0]
    handle = selected['window']
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    if user32.IsIconic(handle):
        user32.ShowWindow(handle, 9)
    accepted = bool(user32.SetForegroundWindow(handle))
    # Cross-thread activation is asynchronous. A no-op message waits for the
    # target queue to process activation before checking the foreground window.
    user32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)
    ]
    user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
    message_result = ctypes.c_size_t()
    responding = bool(user32.SendMessageTimeoutW(
        handle, 0, 0, 0, 2, 1000, ctypes.byref(message_result)
    ))
    # Some clients finish activation after answering WM_NULL. Observe completion
    # for up to one second; do not repeat SetForegroundWindow or steal focus.
    deadline = time.monotonic() + 1
    foreground = int(user32.GetForegroundWindow() or 0)
    while foreground != handle and time.monotonic() < deadline:
        time.sleep(0.01)
        foreground = int(user32.GetForegroundWindow() or 0)
    selected['foreground'] = foreground == handle
    return {'ok': selected['foreground'], 'action': 'focus', 'os_accepted': accepted,
            'window_responding': responding, **selected, 'business_requests_sent': 0}
