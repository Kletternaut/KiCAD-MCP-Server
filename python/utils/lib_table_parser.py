"""
Robust parser for KiCAD fp-lib-table and sym-lib-table files.

Uses sexpdata for proper S-expression parsing instead of regex,
so paths with spaces (e.g. "C:/Program Files/KiCad/...") are
handled correctly on all platforms (Windows, Linux, macOS).
"""

import logging
from pathlib import Path
from typing import Dict, Iterator, Tuple

import sexpdata
from sexpdata import Symbol

logger = logging.getLogger("kicad_interface")


def _str(val: object) -> str:
    """Convert sexpdata Symbol or str to plain string."""
    if isinstance(val, Symbol):
        return str(val)
    return val if isinstance(val, str) else str(val)


def parse_lib_table(table_path: Path) -> Iterator[Tuple[str, str, str]]:
    """Parse a KiCAD lib-table file using sexpdata.

    Yields (nickname, lib_type, uri) tuples for every ``(lib ...)`` entry.
    Handles quoted paths with spaces, unquoted symbols, and all KiCAD
    versions correctly.

    Args:
        table_path: Path to fp-lib-table or sym-lib-table file.

    Yields:
        Tuples of (nickname: str, lib_type: str, uri: str).
    """
    try:
        content = table_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.error(f"Cannot read lib-table {table_path}: {exc}")
        return

    try:
        data = sexpdata.loads(content)
    except Exception as exc:
        logger.error(f"Failed to parse lib-table {table_path}: {exc}")
        return

    if not isinstance(data, list):
        logger.warning(f"Unexpected sexpdata result for {table_path}")
        return

    for item in data[1:]:  # skip the root table symbol (fp_lib_table / sym_lib_table)
        if not isinstance(item, list) or not item:
            continue
        if _str(item[0]) != "lib":
            continue

        # Each lib entry is a list of sub-lists: (name "...") (type ...) (uri "...") …
        props: Dict[str, str] = {}
        for sub in item[1:]:
            if isinstance(sub, list) and len(sub) >= 2:
                key = _str(sub[0])
                props[key] = _str(sub[1])

        nickname = props.get("name", "")
        lib_type = props.get("type", "")
        uri = props.get("uri", "")

        if nickname and uri:
            yield nickname, lib_type, uri
