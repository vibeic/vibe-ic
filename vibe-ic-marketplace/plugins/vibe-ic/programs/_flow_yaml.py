#!/usr/bin/env python3
"""The ONE loader of `flow/phase1_phase2_phase3.yaml` (F18).

WHY
===
The flow yaml is ~645 KB. `yaml.safe_load` runs PyYAML's pure-Python
scanner/parser on it: ~0.37-0.40 s per parse. The libyaml-backed
`yaml.CSafeLoader` builds the same document in ~0.015-0.022 s. Since
e06c227f9 (step_metrics adoption) every gate program's exit parses the flow
yaml to attribute its outcome to a step, so every gate launch paid the
pure-Python price, and one process that asked twice paid it twice.

THE RULE
========
`load(path)` returns exactly what `yaml.safe_load(path.read_text(...))`
returns -- same keys, values and Python types -- by:

  * parsing with `yaml.CSafeLoader` when PyYAML was built with libyaml, and
    with `yaml.SafeLoader` otherwise (the same constructor and resolver
    either way; only the scanner/parser is C). The choice is made per call
    from what the imported `yaml` module offers, so a PyYAML without libyaml
    falls back silently and correctly;
  * parsing at most ONCE per process per (resolved path, mtime_ns, size,
    sha256 of the decoded text). The file is re-read, decoded as the caller
    asked and re-hashed on every call (~2 ms), so an edited file is re-parsed
    even when the edit kept its mtime and size, and callers that decode the
    same bytes to the same text (utf-8 vs locale vs errors="replace" on a
    valid UTF-8 flow) share one parse;
  * handing every caller a DEEP COPY of the cached document (~2 ms), so a
    caller that mutates what it got cannot change what the next caller
    reads -- exactly as with a fresh `safe_load`.

Decoding matches `Path.read_text(encoding=..., errors=...)` (text mode,
universal newlines; `encoding=None` is the locale default). A read or parse
error raises what the old code raised (OSError / UnicodeDecodeError /
yaml.YAMLError / ImportError when PyYAML is absent) and caches nothing.
"""
from __future__ import annotations

import copy
import hashlib
import io
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

#: Where the flow definition lives relative to this file (plugin layout).
DEFAULT_FLOW_YAML = (Path(__file__).resolve().parent.parent / "flow"
                     / "phase1_phase2_phase3.yaml")

_CACHE: Dict[Tuple[Any, ...], Any] = {}
_MAX_ENTRIES = 8
#: Parses actually performed by this process (not cache hits), by loader name.
PARSES: Dict[str, int] = {}


def loader_class():
    """The loader `load` parses with: libyaml's CSafeLoader when present."""
    import yaml                                           # noqa: PLC0415
    return getattr(yaml, "CSafeLoader", None) or yaml.SafeLoader


def _decode(data: bytes, encoding: Optional[str], errors: Optional[str]) -> str:
    # The same text Path.read_text(encoding, errors) produces: a text-mode
    # wrapper, so newline translation and the locale default match it.
    with io.TextIOWrapper(io.BytesIO(data), encoding=encoding,
                          errors=errors) as fh:
        return fh.read()


def load(path: Optional[os.PathLike] = None, *, encoding: Optional[str] = None,
         errors: Optional[str] = None) -> Any:
    """`yaml.safe_load(Path(path).read_text(encoding=, errors=))`, parsed
    once per process per content and with libyaml when available."""
    import yaml                                           # noqa: PLC0415
    p = Path(path) if path is not None else DEFAULT_FLOW_YAML
    st = os.stat(p)
    text = _decode(p.read_bytes(), encoding, errors)
    # Keyed on the DECODED text: callers that read the same file with
    # different encoding/errors share one parse whenever the text is the same
    # (it is, for a valid UTF-8 flow), and never when it is not.
    key = (str(p.resolve()), st.st_mtime_ns, st.st_size,
           hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest())
    if key not in _CACHE:
        loader = loader_class()
        doc = yaml.load(text, Loader=loader)              # noqa: S506 - safe loaders only
        PARSES[loader.__name__] = PARSES.get(loader.__name__, 0) + 1
        for old in [k for k in _CACHE if k[0] == key[0]]:
            del _CACHE[old]     # a superseded version of this file
        while len(_CACHE) >= _MAX_ENTRIES:
            del _CACHE[next(iter(_CACHE))]
        _CACHE[key] = doc
    result = copy.deepcopy(_CACHE[key])
    import _path_layout
    if _path_layout.active_rtl_input() != "structured" and isinstance(result, dict):
        from step_required_inputs_check import input_contract
        result["steps"] = [input_contract(row, _path_layout.active_rtl_input())
                           for row in result.get("steps", [])]
    return result


def clear_cache() -> None:
    _CACHE.clear()
    PARSES.clear()


def step_requirements(flow: dict) -> dict[str, dict]:
    """Extract declared gates and outputs without granting source authority.

    Installed Default callers use the bundled flow. Git-bound candidate
    callers verify their source separately before using these same contracts.
    """
    requirements = {}
    for step in flow['steps']:
        gates = set()
        gate = step.get('gate') or {}
        for clause in [gate, *gate.get('all_of', [])]:
            for key in ('program_exit_zero', 'advisory_program_exit_zero',
                        'optional_program_exit_zero'):
                value = clause.get(key) if isinstance(clause, dict) else None
                command = value if isinstance(value, str) else (
                    value.get('command', '') if isinstance(value, dict) else '')
                if command:
                    gates.add(Path(command.split()[0]).name)
        requirements[str(step.get('id'))] = dict(
            gates=frozenset(gates),
            outputs=tuple(step.get('required_outputs') or ()),
        )
    return requirements


def ordered_step_ids(*, stages=None, execution_stages=None, execution_tracks=None) -> tuple[str, ...]:
    """The declared execution order; step labels are never numeric ranks."""
    selected = None if stages is None else frozenset(stages)
    execution = None if execution_stages is None else frozenset(execution_stages)
    tracks = None if execution_tracks is None else frozenset(execution_tracks)
    return tuple(str(row['id']) for row in load()['steps']
                 if (selected is None or row.get('stage') in selected)
                 and (execution is None or row.get('execution_stage') in execution)
                 and (tracks is None or row.get('execution_track', 'default') in tracks))
