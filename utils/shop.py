"""
Character shop client — fetch catalog, download/update/delete character packs.

The remote catalog is a JSON file served at the configured ``shop_url``.
Each entry describes a downloadable character pack (zip) with preview image.
"""

import io
import json
import logging
import os
import shutil
import zipfile
from dataclasses import dataclass, field
from typing import Callable, Optional

import requests

log = logging.getLogger(__name__)

_TIMEOUT = 15  # seconds for HTTP requests


# ── data models ────────────────────────────────────────────────────────

@dataclass
class ShopCharacter:
    """A character available in the remote shop."""
    id: str
    name: str
    version: str
    author: str = ""
    description: str = ""
    preview_url: str = ""
    download_url: str = ""
    size_mb: float = 0.0
    tags: list[str] = field(default_factory=list)


# ── catalog ────────────────────────────────────────────────────────────

def fetch_shop_catalog(shop_url: str) -> list[ShopCharacter]:
    """GET the remote shop.json and return parsed entries.

    Returns an empty list on any network / parse error.
    """
    try:
        resp = requests.get(shop_url, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("Failed to fetch shop catalog from %s: %s", shop_url, exc)
        return []

    characters: list[ShopCharacter] = []
    for entry in data.get("characters", []):
        try:
            characters.append(ShopCharacter(
                id=entry["id"],
                name=entry["name"],
                version=entry.get("version", "0.0.0"),
                author=entry.get("author", ""),
                description=entry.get("description", ""),
                preview_url=entry.get("preview_url", ""),
                download_url=entry.get("download_url", ""),
                size_mb=float(entry.get("size_mb", 0)),
                tags=entry.get("tags", []),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            log.warning("Skipping malformed shop entry: %s", exc)
    return characters


def fetch_preview_bytes(url: str) -> Optional[bytes]:
    """Download a preview image and return raw bytes, or None on failure."""
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.content
    except Exception as exc:
        log.debug("Preview download failed (%s): %s", url, exc)
        return None


# ── download / extract ─────────────────────────────────────────────────

def download_character(
    char: ShopCharacter,
    dest_dir: str,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> str:
    """Download a character zip and extract it into *dest_dir*.

    *progress_cb(bytes_downloaded, total_bytes)* is called during streaming.
    Returns the absolute path to the extracted character folder.
    Raises on failure.
    """
    os.makedirs(dest_dir, exist_ok=True)
    resp = requests.get(char.download_url, stream=True, timeout=60)
    resp.raise_for_status()

    total = int(resp.headers.get("content-length", 0))
    buf = io.BytesIO()
    downloaded = 0

    for chunk in resp.iter_content(chunk_size=8192):
        buf.write(chunk)
        downloaded += len(chunk)
        if progress_cb:
            progress_cb(downloaded, total)

    buf.seek(0)

    # Validate zip
    if not zipfile.is_zipfile(buf):
        raise ValueError("Downloaded file is not a valid zip archive")

    buf.seek(0)
    with zipfile.ZipFile(buf) as zf:
        # Validate: must contain character.json somewhere
        names = zf.namelist()
        has_manifest = any(n.endswith("character.json") for n in names)
        if not has_manifest:
            raise ValueError("Zip does not contain a character.json")

        zf.extractall(dest_dir)

    # The zip should contain a folder named after the character id
    extracted = os.path.join(dest_dir, char.id)
    if not os.path.isdir(extracted):
        # Try to find whatever top-level folder was extracted
        top_dirs = {n.split("/")[0] for n in names if "/" in n}
        if len(top_dirs) == 1:
            actual = os.path.join(dest_dir, top_dirs.pop())
            if os.path.isdir(actual):
                extracted = actual

    log.info("Extracted character '%s' to %s", char.name, extracted)
    return extracted


# ── delete ─────────────────────────────────────────────────────────────

def delete_character(char_id: str, sprites_dir: str) -> bool:
    """Delete a downloaded character folder.

    Returns True if deleted, False if not found or error.
    """
    target = os.path.join(sprites_dir, char_id)
    if not os.path.isdir(target):
        log.warning("Cannot delete '%s': folder not found at %s", char_id, target)
        return False
    try:
        shutil.rmtree(target)
        log.info("Deleted character folder: %s", target)
        return True
    except OSError as exc:
        log.error("Failed to delete '%s': %s", target, exc)
        return False


# ── version comparison ─────────────────────────────────────────────────

def needs_update(installed_version: Optional[str], shop_version: str) -> bool:
    """Return True if the shop version is newer than the installed one.

    Uses simple tuple comparison of version segments.
    """
    if not installed_version:
        return True
    try:
        inst = tuple(int(x) for x in installed_version.split("."))
        shop = tuple(int(x) for x in shop_version.split("."))
        return shop > inst
    except (ValueError, AttributeError):
        # If versions are not parseable, treat as needing update
        return installed_version != shop_version
