"""Response parsers for the routines workflow engine.

Supports JSON (dot-path), XML (tag path), and Regex extraction.
"""

import json
import logging
import re
import xml.etree.ElementTree as ET
from typing import Any

log = logging.getLogger("routines.parsers")


def parse_value(data: str, parser: str, query: str) -> str:
    """Parse *data* using the specified *parser* and *query*.

    Returns the extracted value as a string, or raises ``ValueError``
    on failure.
    """
    parser = parser.lower().strip()
    if parser == "json":
        return parse_json(data, query)
    if parser == "xml":
        return parse_xml(data, query)
    if parser == "regex":
        return parse_regex(data, query)
    raise ValueError(f"Unknown parser: {parser!r}")


def parse_json(data: str, query: str) -> str:
    """Navigate a JSON string using a dot-path query.

    Supports object keys and integer array indices::

        "main.temp"       → obj["main"]["temp"]
        "items.0.name"    → obj["items"][0]["name"]
    """
    try:
        obj: Any = json.loads(data)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"JSON decode error: {exc}") from exc

    parts = query.split(".")
    current = obj
    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                raise ValueError(f"Key '{part}' not found in JSON object")
            current = current[part]
        elif isinstance(current, list):
            try:
                idx = int(part)
            except ValueError:
                raise ValueError(f"Expected integer index for list, got '{part}'")
            if idx < 0 or idx >= len(current):
                raise ValueError(f"Index {idx} out of range (list length {len(current)})")
            current = current[idx]
        else:
            raise ValueError(f"Cannot navigate into {type(current).__name__} with key '{part}'")

    return str(current)


def parse_xml(data: str, query: str) -> str:
    """Extract text from an XML string using a tag path.

    Uses ``xml.etree.ElementTree.find()`` with the given path.
    Example: ``"channel/item/title"``
    """
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"XML parse error: {exc}") from exc

    # Try direct find first
    elem = root.find(query)
    if elem is None:
        # Try searching from root tag as prefix (e.g. query might not include root)
        # If root.tag matches the first segment, strip it
        parts = query.split("/")
        if parts and parts[0] == root.tag:
            sub_query = "/".join(parts[1:])
            if sub_query:
                elem = root.find(sub_query)
            else:
                elem = root

    if elem is None:
        raise ValueError(f"XML element not found: {query!r}")

    text = elem.text
    return str(text).strip() if text else ""


def parse_regex(data: str, query: str) -> str:
    """Extract text from a string using a regex pattern.

    Returns the first captured group if present, otherwise the full
    match.
    """
    try:
        match = re.search(query, data, re.DOTALL)
    except re.error as exc:
        raise ValueError(f"Regex error: {exc}") from exc

    if not match:
        raise ValueError(f"Regex pattern did not match: {query!r}")

    # Return first group if captured, otherwise full match
    groups = match.groups()
    if groups:
        return str(groups[0]) if groups[0] is not None else ""
    return match.group(0)
