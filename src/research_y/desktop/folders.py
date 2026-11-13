"""Host-only native folder selection for the isolated NiceGUI/pywebview experiment.

A browser may request the operating-system dialog, but may NOT submit its
result, a project path, or a directory to the application. The user-selected
path is read exclusively from the native-window API in the trusted host.
"""
from __future__ import annotations

from pathlib import Path

from research_y.export_files import Directory, ExportFileError


class NativeFolderError(ValueError):
    """Static diagnostic, never an input path or native exception string."""

    def __init__(self, code: str):
        super().__init__(code if code in {
            'native_selection_invalid', 'native_selection_unsafe',
            'native_dialog_unavailable',
        } else 'native_selection_invalid')


def checked_folder(selection) -> Path | None:
    """Accept one actual existing, unlinked local directory or cancellation.

    Neither browser text nor a URL is a valid dialog result. Reject all
    ancestor symlinks/junctions/reparse points through the existing export
    directory guard, without resolving an unsafe path and treating its target
    as user-selected. This cannot sandbox a hostile same-account process.
    """
    if selection is None or selection == () or selection == []:
        return None
    if (type(selection) not in (tuple, list) or len(selection) != 1
            or type(selection[0]) is not str):
        raise NativeFolderError('native_selection_invalid')
    path = Path(selection[0])
    if not path.is_absolute() or '..' in path.parts or '\x00' in selection[0]:
        raise NativeFolderError('native_selection_invalid')
    try:
        with Directory(path):
            return path
    except (ExportFileError, OSError, ValueError, TypeError):
        raise NativeFolderError('native_selection_unsafe') from None


async def select_from_native_window(window) -> Path | None:
    """Open pywebview's real OS folder picker, not a browser file upload.

    The asynchronous NiceGUI native-window proxy exposes the pywebview
    create_file_dialog method; the engine's result never comes from a
    request body, query, browser cookie or client-side script argument.
    """
    try:
        import webview  # optional native-only feasibility dependency
        result = await window.create_file_dialog(
            dialog_type=webview.FileDialog.FOLDER, allow_multiple=False)
    except Exception:
        raise NativeFolderError('native_dialog_unavailable') from None
    return checked_folder(result)


async def select_conference_document(window):
    try:
        import webview
        result = await window.create_file_dialog(dialog_type=webview.FileDialog.OPEN, allow_multiple=False,
                                                 file_types=("JATS XML (*.xml;*.nxml)",))
    except Exception:
        raise NativeFolderError("native_dialog_unavailable") from None
    if not result:
        return None
    if type(result) not in (tuple,list) or len(result)!=1 or type(result[0]) is not str:
        raise NativeFolderError("native_selection_invalid")
    path = Path(result[0])
    if not path.is_absolute() or path.suffix.lower() not in {".xml",".nxml"}:
        raise NativeFolderError("native_selection_invalid")
    checked_folder([str(path.parent)])
    return path
