"""
Markdown data loader — shared utility for all tool files.

Parses structured data from Markdown tables in the /data directory.
Each tool calls load() + parse_table() or parse_sections() at module
import time so the data is read once and cached in module-level variables.
"""

import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


# ── Low-level row parser ───────────────────────────────────────────────────────

def _parse_row(line: str) -> list[str]:
    """Split a markdown table row on '|', strip whitespace, drop boundary empties."""
    cells = line.split("|")
    if cells and cells[0].strip() == "":
        cells = cells[1:]
    if cells and cells[-1].strip() == "":
        cells = cells[:-1]
    return [c.strip() for c in cells]


def _is_separator(line: str) -> bool:
    """True if line is a markdown table separator (e.g. |---|:---|)."""
    s = line.strip()
    return bool(s) and "|" in s and bool(re.match(r"^[\|\s\-:]+$", s))


# ── Public API ────────────────────────────────────────────────────────────────

def load(filename: str) -> str:
    """Read a file from the data directory and return its text."""
    return (DATA_DIR / filename).read_text(encoding="utf-8")


def parse_table(text: str) -> list[dict]:
    """
    Parse the first markdown table found in *text*.

    Returns a list of dicts keyed by the column headers in the first
    non-separator row that contains pipes.
    """
    lines = text.splitlines()
    header: list[str] | None = None
    rows: list[dict] = []

    for line in lines:
        s = line.strip()
        if not s or "|" not in s:
            continue
        if _is_separator(s):
            continue
        cells = _parse_row(s)
        if header is None:
            header = cells
        elif len(cells) == len(header):
            rows.append(dict(zip(header, cells)))

    return rows


def parse_sections(text: str) -> dict[str, list[dict]]:
    """
    Split markdown on '## Heading' boundaries and parse each section's table.

    Returns {section_name: [row_dicts]}.  Sections without a markdown table
    produce an empty list.  Content before the first '## ' heading is ignored.
    """
    sections: dict[str, list[dict]] = {}
    current_name: str | None = None
    current_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("## "):
            if current_name is not None:
                sections[current_name] = parse_table("\n".join(current_lines))
            current_name = line[3:].strip()
            current_lines = []
        elif current_name is not None:
            current_lines.append(line)

    if current_name is not None:
        sections[current_name] = parse_table("\n".join(current_lines))

    return sections
