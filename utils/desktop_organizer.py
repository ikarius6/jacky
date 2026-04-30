"""Desktop organizer — list, categorize, and move loose Desktop files.

Pure utility module with no Qt dependencies.  Used by the routine engine
and the pet_window confirmation flow.
"""

import json
import logging
import os
import pathlib
import shutil
from typing import Any, Dict, List, Optional

log = logging.getLogger("desktop_organizer")

# Files to always ignore when scanning the Desktop
_SKIP_NAMES = {".DS_Store", "desktop.ini", "Thumbs.db"}

# Extension → folder mapping used when LLM is unavailable
_EXT_CATEGORIES: Dict[str, str] = {
    # Images
    ".jpg": "Images", ".jpeg": "Images", ".png": "Images", ".gif": "Images",
    ".bmp": "Images", ".svg": "Images", ".webp": "Images", ".ico": "Images",
    ".tiff": "Images", ".tif": "Images", ".heic": "Images", ".heif": "Images",
    ".raw": "Images", ".psd": "Images", ".ai": "Images",
    # Documents
    ".pdf": "Documents", ".doc": "Documents", ".docx": "Documents",
    ".xls": "Documents", ".xlsx": "Documents", ".ppt": "Documents",
    ".pptx": "Documents", ".odt": "Documents", ".ods": "Documents",
    ".odp": "Documents", ".txt": "Documents", ".rtf": "Documents",
    ".csv": "Documents", ".md": "Documents",
    # Videos
    ".mp4": "Videos", ".mkv": "Videos", ".avi": "Videos", ".mov": "Videos",
    ".wmv": "Videos", ".flv": "Videos", ".webm": "Videos", ".m4v": "Videos",
    # Audio
    ".mp3": "Audio", ".wav": "Audio", ".flac": "Audio", ".aac": "Audio",
    ".ogg": "Audio", ".wma": "Audio", ".m4a": "Audio", ".opus": "Audio",
    # Archives
    ".zip": "Archives", ".rar": "Archives", ".7z": "Archives",
    ".tar": "Archives", ".gz": "Archives", ".bz2": "Archives",
    ".xz": "Archives",
    # Installers
    ".exe": "Installers", ".msi": "Installers", ".dmg": "Installers",
    ".pkg": "Installers", ".deb": "Installers", ".rpm": "Installers",
    ".appimage": "Installers",
    # Code / scripts
    ".py": "Code", ".js": "Code", ".ts": "Code", ".html": "Code",
    ".css": "Code", ".json": "Code", ".xml": "Code", ".yaml": "Code",
    ".yml": "Code", ".sh": "Code", ".bat": "Code", ".ps1": "Code",
    ".java": "Code", ".cpp": "Code", ".c": "Code", ".h": "Code",
    ".cs": "Code", ".go": "Code", ".rs": "Code", ".rb": "Code",
    # Shortcuts
    ".lnk": "Shortcuts", ".url": "Shortcuts",
}

_DEFAULT_FOLDER = "Misc"


# ── Scanning ──────────────────────────────────────────────────────────

def _resolve_desktop() -> pathlib.Path:
    """Return the actual Desktop path, respecting OneDrive/shell redirection."""
    import sys
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            ) as key:
                raw, _ = winreg.QueryValueEx(key, "Desktop")
                expanded = pathlib.Path(os.path.expandvars(raw))
                if expanded.is_dir():
                    return expanded
        except OSError:
            pass
    # Fallback chain
    for candidate in (
        pathlib.Path.home() / "OneDrive" / "Desktop",
        pathlib.Path.home() / "OneDrive" / "Escritorio",
        pathlib.Path.home() / "Desktop",
        pathlib.Path.home() / "Escritorio",
    ):
        if candidate.is_dir():
            return candidate
    return pathlib.Path.home() / "Desktop"


def list_folder_files(folder: pathlib.Path) -> List[Dict[str, str]]:
    """Return a JSON-serializable list of loose files in *folder*.

    Each entry: ``{"name": "photo.jpg", "ext": ".jpg"}``.
    Existing sub-folders and hidden/system files are skipped.
    """
    entries: List[Dict[str, str]] = []
    if not folder.is_dir():
        log.warning("Folder path does not exist: %s", folder)
        return entries
    for p in sorted(folder.iterdir()):
        if not p.is_file():
            continue
        if p.name in _SKIP_NAMES or p.name.startswith("."):
            continue
        entries.append({"name": p.name, "ext": p.suffix.lower()})
    return entries


def list_desktop_files(desktop: Optional[pathlib.Path] = None) -> List[Dict[str, str]]:
    """Return a JSON-serializable list of loose files on the Desktop.

    Each entry: ``{"name": "photo.jpg", "ext": ".jpg"}``.
    Existing sub-folders and hidden/system files are skipped.
    """
    if desktop is None:
        desktop = _resolve_desktop()
    return list_folder_files(desktop)


# ── Rule-based categorization (fallback when LLM is off) ─────────────

def categorize_by_extension(files: List[Dict[str, str]]) -> Dict[str, List[str]]:
    """Bucket file names into folders based on extension.

    Returns ``{"Images": ["a.jpg", ...], "Documents": ["b.pdf", ...], ...}``.
    """
    plan: Dict[str, List[str]] = {}
    for f in files:
        folder = _EXT_CATEGORIES.get(f["ext"], _DEFAULT_FOLDER)
        plan.setdefault(folder, []).append(f["name"])
    return plan


# ── Execution ─────────────────────────────────────────────────────────

def execute_organize_plan(
    plan: Dict[str, List[str]],
    desktop: Optional[pathlib.Path] = None,
    undo_log_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Move files into sub-folders according to *plan*.

    Parameters
    ----------
    plan : dict
        ``{"FolderName": ["file1.ext", ...], ...}``
    desktop : Path, optional
        Desktop directory.  Defaults to ``~/Desktop``.
    undo_log_path : str, optional
        If given, write a JSON undo log to this path.

    Returns
    -------
    dict
        ``{"moved": [...], "skipped": [...], "errors": [...]}``
    """
    if desktop is None:
        desktop = _resolve_desktop()

    moved: List[Dict[str, str]] = []
    skipped: List[str] = []
    errors: List[Dict[str, str]] = []

    for folder_name, filenames in plan.items():
        target_dir = desktop / folder_name
        for fname in filenames:
            src = desktop / fname
            if not src.is_file():
                skipped.append(fname)
                continue
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                dst = target_dir / fname
                # Avoid overwrite — append suffix if destination exists
                if dst.exists():
                    stem = src.stem
                    suffix = src.suffix
                    counter = 1
                    while dst.exists():
                        dst = target_dir / f"{stem}_{counter}{suffix}"
                        counter += 1
                shutil.move(str(src), str(dst))
                moved.append({"src": str(src), "dst": str(dst)})
                log.debug("MOVED %s -> %s", src, dst)
            except PermissionError as exc:
                log.warning("Permission denied moving '%s': %s", fname, exc)
                errors.append({"file": fname, "error": f"PermissionError: {exc}"})
            except OSError as exc:
                log.warning("OS error moving '%s': %s", fname, exc)
                errors.append({"file": fname, "error": str(exc)})

    # Write undo log
    if undo_log_path and moved:
        try:
            undo_path = pathlib.Path(undo_log_path)
            undo_path.parent.mkdir(parents=True, exist_ok=True)
            undo_path.write_text(json.dumps(moved, indent=2, ensure_ascii=False),
                                 encoding="utf-8")
            log.info("Undo log written to %s", undo_log_path)
        except OSError as exc:
            log.warning("Failed to write undo log: %s", exc)

    result = {"moved": moved, "skipped": skipped, "errors": errors}
    log.info("ORGANIZE_DONE moved=%d skipped=%d errors=%d",
             len(moved), len(skipped), len(errors))
    return result


def format_plan_summary(plan: Dict[str, List[str]]) -> str:
    """Build a human-readable summary of the plan for the LLM or fallback.

    Example: ``"Images (5), Documents (3), Misc (2)"``
    """
    parts = []
    total = 0
    for folder, files in sorted(plan.items()):
        parts.append(f"{folder} ({len(files)})")
        total += len(files)
    return f"{total} archivos → " + ", ".join(parts)
