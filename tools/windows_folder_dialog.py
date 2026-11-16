"""Operate only the disposable lifecycle fixture's own native folder dialog."""
from __future__ import annotations

import time
from pathlib import Path
import ctypes
from ctypes import wintypes


def choose_fixture_folder(process_ids, folder):
    import clr
    from System.Runtime.InteropServices import RuntimeEnvironment
    from System import IntPtr
    wpf = Path(RuntimeEnvironment.GetRuntimeDirectory()) / "WPF"
    for assembly in ("UIAutomationTypes", "UIAutomationClient"):
        clr.AddReference(str(wpf / (assembly + ".dll")))
    from System.Windows.Automation import (
        AutomationElement as Element, ControlType,
        PropertyCondition, SelectionItemPattern, TreeScope, ValuePattern,
    )

    def by_id(value):
        return PropertyCondition(Element.AutomationIdProperty, value)

    user = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user.IsWindowVisible.argtypes = (wintypes.HWND,)
    user.IsWindowEnabled.argtypes = (wintypes.HWND,)
    user.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user.IsWindow.argtypes = (wintypes.HWND,)
    user.EnumWindows.argtypes = (callback_type, wintypes.LPARAM)
    user.EnumChildWindows.argtypes = (wintypes.HWND, callback_type, wintypes.LPARAM)
    handles = []
    owned_windows = set()
    dialog_controls = set()
    input_controls = set()
    navigating = False

    @callback_type
    def collect_control(handle, _):
        name = ctypes.create_unicode_buffer(256)
        user.GetClassNameW(handle, name, len(name))
        dialog_controls.add(name.value)
        return True

    @callback_type
    def collect(handle, _):
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        if pid.value in process_ids:
            name = ctypes.create_unicode_buffer(256)
            user.GetClassNameW(handle, name, len(name))
            owned_windows.add((name.value, bool(user.IsWindowVisible(handle)), bool(user.IsWindowEnabled(handle))))
            if name.value == "#32770" and user.IsWindowVisible(handle) and user.IsWindowEnabled(handle):
                handles.append(handle)
        return True

    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        handles.clear()
        user.EnumWindows(collect, 0)
        if len(handles) == 1:
            dialog = Element.FromHandle(IntPtr(handles[0]))
            # Hosted Windows and desktop editions can use different owner
            # chains. Identify Explorer's actual file list inside the single
            # enabled modal of the isolated fixture process on either edition.
            dialog_controls.clear()
            user.EnumChildWindows(handles[0], collect_control, 0)
            button = dialog.FindFirst(TreeScope.Descendants, by_id("2" if folder is None else "1"))
            if "SHELLDLL_DefView" in dialog_controls and button is not None:
                if folder is not None:
                    entries = dialog.FindAll(TreeScope.Descendants, PropertyCondition(
                        Element.NameProperty, folder.name))
                    items = [e for e in entries if e.Current.ControlType in
                             (ControlType.ListItem, ControlType.DataItem)]
                    if len(items) != 1:
                        if not navigating:
                            edits = dialog.FindAll(TreeScope.Descendants, PropertyCondition(
                                Element.ControlTypeProperty, ControlType.Edit))
                            for edit in edits:
                                input_controls.add(edit.Current.AutomationId)
                                if edit.Current.AutomationId == "1152":  # Win32 edt1
                                    edit.GetCurrentPattern(ValuePattern.Pattern).SetValue(str(folder.parent))
                                    user.PostMessageW(handles[0], 0x0111, 1, button.Current.NativeWindowHandle)
                                    navigating = True
                                    break
                        time.sleep(.1)
                        continue
                    items[0].GetCurrentPattern(SelectionItemPattern.Pattern).Select()
                if folder is None:
                    user.PostMessageW(handles[0], 0x0010, 0, 0)  # WM_CLOSE
                else:
                    user.PostMessageW(handles[0], 0x0111, 1, button.Current.NativeWindowHandle)  # WM_COMMAND / IDOK
                selected_dialog = handles[0]
                while time.monotonic() < deadline:
                    if not user.IsWindow(selected_dialog) or not user.IsWindowVisible(selected_dialog):
                        return
                    time.sleep(.1)
                raise RuntimeError("fixture_native_dialog_did_not_close")
        time.sleep(.1)
    raise RuntimeError(f"fixture_native_folder_dialog_unavailable: {len(handles)} active owned dialogs; "
                       f"test process window classes, visibility and enabled state: {sorted(owned_windows)}; "
                       f"dialog control classes: {sorted(dialog_controls)}; edit control IDs: {sorted(input_controls)}")
