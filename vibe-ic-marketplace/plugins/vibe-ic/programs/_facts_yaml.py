#!/usr/bin/env python3
"""
_facts_yaml.py — shared YAML reader for `facts.yaml` (v0.119.70 / Wave 42).

The Wave 42 fault-injection audit found that several gates read
`facts.yaml` with substring `grep` regexes. That approach is fooled by
trivial attacks:
  - `# no_fsm: true`               (commented out)
  - `metadata: { no_fsm: true }`   (nested below another key)
  - `# example: no_command_protocol: true   (illustration only)`

Every such fall-through let a fault-injected escape boolean silence a
gate that should have FAILed.

This helper centralises a real YAML parser (PyYAML, already a project
dependency via requirements) and exposes a minimal, top-level-only API:

    facts = read_facts_yaml(project_dir)
    if get_top_level_bool(facts, "no_fsm"):
        ...

Top-level only means: only direct keys of the document root count. A
boolean nested under any other mapping is ignored. A YAML comment is
ignored. Bad YAML returns an empty dict (fail-closed: gates treat
missing escapes as "absent" and run their normal logic).

Importing this module is cheap: PyYAML is loaded lazily inside
`read_facts_yaml`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional


def read_facts_yaml(project_dir: Path | str) -> Dict[str, Any]:
    """Parse `<project_dir>/facts.yaml` with a real YAML parser.

    Returns an empty dict on any of:
      - file does not exist
      - file is not readable
      - YAML is malformed
      - top-level value is not a mapping

    Never raises — callers can rely on a dict-shaped return.
    """
    project = Path(project_dir)
    facts = project / "facts.yaml"
    if not facts.is_file():
        return {}
    try:
        text = facts.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}
    try:
        import yaml  # type: ignore
    except ImportError:
        # PyYAML missing — fail-closed: pretend the file is unreadable.
        # Substring fall-back is intentionally NOT used here because
        # that is exactly the attack vector Wave 42 is closing.
        return {}
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def get_top_level_bool(
    facts: Dict[str, Any],
    key: str,
    default: bool = False,
) -> bool:
    """Return the top-level boolean value for `key`, else `default`.

    Only true booleans count — strings like "true" or numbers like 1 do
    NOT satisfy this. This is deliberate: an attack that types
    `no_fsm: "true"` (string) will not fool the helper. Callers who
    want lenient parsing can call `get_top_level_truthy` instead.
    """
    if not isinstance(facts, dict):
        return default
    v = facts.get(key, default)
    if isinstance(v, bool):
        return v
    return default


def get_top_level_truthy(
    facts: Dict[str, Any],
    key: str,
    default: bool = False,
) -> bool:
    """Lenient sibling of `get_top_level_bool` — accepts the YAML
    canonical truthy spellings (`true`, `yes`, `on`, `1`).

    Useful for gates that historically grep'd these strings; gives
    them an opt-in upgrade path without re-introducing substring
    matching across the whole file.
    """
    if not isinstance(facts, dict):
        return default
    v = facts.get(key, default)
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v) and not isinstance(v, bool)
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes", "on", "1")
    return default


def get_top_level(
    facts: Dict[str, Any],
    key: str,
    default: Any = None,
) -> Any:
    """Return the raw top-level value (any type) for `key`."""
    if not isinstance(facts, dict):
        return default
    return facts.get(key, default)


__all__ = [
    "read_facts_yaml",
    "get_top_level_bool",
    "get_top_level_truthy",
    "get_top_level",
]
