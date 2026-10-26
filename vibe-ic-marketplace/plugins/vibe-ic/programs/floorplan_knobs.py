#!/usr/bin/env python3
"""CR-3 L9 floorplan knob parsing and pinned flow defaults."""
from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import _container_exec as _cex
import _path_layout as _pl

# CR-3: the two L9 knobs have separate units and separate consumers.
# FP_CORE_UTIL is a percentage for core area; PL_TARGET_DENSITY is a fraction
# for global placement. The keys have independent input declarations.
_L9_PL_DENSITY_RE = re.compile(
    r"PL_TARGET_DENSITY`?\s*\|\s*\*{0,2}\s*(0?\.\d+|\d+(?:\.\d+)?)\s*\*{0,2}\s*\|",
    re.IGNORECASE)
# For an FP_CORE_UTIL range, the lower declared endpoint is routing safer.
def md_table_column_numbers(text: str, key: str, row_key: str = ""):
    """Every numeric value under a markdown-table COLUMN whose header names
    ``key``, in row order. PURE (unit-tested, no I/O).

    Both row-oriented key/value and PDK-keyed column tables are supported.

    Tables are scoped as BLOCKS (contiguous runs of `|` lines) and the column
    index is re-resolved per block, preventing a header from leaking into a
    later table with a different meaning.

    ``row_key`` (optional) keeps only rows whose FIRST cell contains it, so a
    per-PDK table returns only the matching row; an unmatched row yields none.

    A range like ``35-45%`` yields 35 — the low, routing-safest end of the
    declared band. chip-AGNOSTIC.
    """
    import re as _re
    out = []
    lines = text.splitlines()
    i, n = 0, len(lines)
    while i < n:
        if not lines[i].strip().startswith("|"):
            i += 1
            continue
        block = []
        while i < n and lines[i].strip().startswith("|"):
            block.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
            i += 1
        if len(block) < 2:
            continue
        header = block[0]
        col = None
        for j, c in enumerate(header):
            if _re.search(r"\b" + _re.escape(key) + r"\b", c, _re.IGNORECASE):
                col = j
                break
        if col is None:
            continue
        for cells in block[1:]:
            if all(_re.fullmatch(r":?-{2,}:?", c or "") for c in cells if c):
                continue                    # the |---|---| separator row
            if row_key:
                # A PDK id and a table's PDK label rarely match character for
                # character when one spelling includes a variant suffix,
                # so compare on alphanumerics with a BIDIRECTIONAL prefix test:
                # either may be the more specific spelling of the same PDK.
                _rk = _re.sub(r"[^a-z0-9]", "", row_key.lower())
                _rc = _re.sub(r"[^a-z0-9]", "", (cells[0] if cells else "").lower())
                if not (_rk and _rc
                        and (_rk.startswith(_rc) or _rc.startswith(_rk))):
                    continue
            if col < len(cells):
                m = _re.search(r"(\d+(?:\.\d+)?)", cells[col])
                if m:
                    out.append(float(m.group(1)))
    return out


_L9_FP_CORE_UTIL_RE = re.compile(
    r"FP_CORE_UTIL`?\s*\|\s*\*{0,2}\s*(\d+(?:\.\d+)?)\s*"
    r"(?:[-–~]|\bto\b)?\s*(?:\d+(?:\.\d+)?)?\s*%?[^|\n]*\|",
    re.IGNORECASE)
_INPUT_CORE_UTIL_RE = re.compile(
    r"\b(?:target\s+)?core\s+utilization\s*[:=]\s*(\d+(?:\.\d+)?)\s*%",
    re.IGNORECASE)
def _l9_declared_floorplan_knob(project: Path, pdk: str,
                                key: str) -> Optional[float]:
    """Read one L9 floorplan knob without transferring it to the other knob."""
    if key == "FP_CORE_UTIL":
        pattern, maximum, scale = _L9_FP_CORE_UTIL_RE, 100.0, 100.0
    elif key == "PL_TARGET_DENSITY":
        pattern, maximum, scale = _L9_PL_DENSITY_RE, 1.0, 1.0
    else:
        raise ValueError(f"unknown floorplan knob: {key}")
    roots = [project / "input" / "docs", _pl.generated_docs_dir(project)]
    for root in roots:
        if not root.is_dir():
            continue
        for p in (sorted(root.glob("L9*")) + sorted(root.glob("*constraint*"))
                  + sorted(root.glob("*floorplan*"))):
            try:
                txt = p.read_text(errors="ignore")
            except OSError:
                continue
            for m in pattern.finditer(txt):
                try:
                    v = float(m.group(1))
                except ValueError:
                    continue
                if 0.0 < v <= maximum:
                    return v / scale
            # The same key may be a table column keyed by the PDK family.
            _rk = (pdk or "").strip()
            if _rk:
                for v in md_table_column_numbers(txt, key, _rk):
                    if 0.0 < v <= maximum:
                        return v / scale
    if key == "FP_CORE_UTIL":
        # Ordinary input documents need not use an L9 filename. Reuse the
        # established design-input reader; this percentage never sets density.
        import floorplan_contract as _fpc
        for _rel, _path, text in _fpc._iter_input_files(project):
            for match in _INPUT_CORE_UTIL_RE.finditer(text):
                value = float(match.group(1))
                if 0.0 < value <= 100.0:
                    return value / 100.0
    return None


def _l19_declared_die_util(project: Path,
                           pdk: str = "") -> Optional[float]:
    """Resolve L19 FP_CORE_UTIL through LibreLane's existing consumer."""
    path = _pl.generated_docs_dir(project) / "L19_CONSTRAINTS_PDK.json"
    if not path.is_file():
        return None
    try:
        l19 = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("FP_CORE_UTIL_L19_INVALID") from exc
    if not isinstance(l19, dict):
        raise ValueError("FP_CORE_UTIL_L19_INVALID")
    import librelane_contract as _ll
    settings, _sources = _ll._declared_flow_settings(l19, pdk)
    if "FP_CORE_UTIL" not in settings:
        return None
    value = settings["FP_CORE_UTIL"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("FP_CORE_UTIL_L19_INVALID")
    percentage = float(value)
    if not math.isfinite(percentage) or not 0.0 < percentage <= 100.0:
        raise ValueError("FP_CORE_UTIL_L19_RANGE")
    return percentage / 100.0


def _l9_declared_die_util(project: Path,
                          pdk: str = "") -> Optional[float]:
    """The L19/L9 `FP_CORE_UTIL` core-area target as one fraction.

    L19 is the consuming-layer contract.  A still-present L9 declaration may
    corroborate it, but disagreement is an authority conflict, never
    precedence.  Placement density remains on its independent reader.
    """
    l19_value = _l19_declared_die_util(project, pdk)
    l9_value = _l9_declared_floorplan_knob(project, pdk, "FP_CORE_UTIL")
    if (l19_value is not None and l9_value is not None
            and not math.isclose(l19_value, l9_value,
                                 rel_tol=0.0, abs_tol=1e-12)):
        raise ValueError("FP_CORE_UTIL_AUTHORITY_CONFLICT")
    return l19_value if l19_value is not None else l9_value


def _l9_declared_place_density(project: Path,
                               pdk: str = "") -> Optional[float]:
    """The L9 `PL_TARGET_DENSITY` placement target, never a core-area input."""
    return _l9_declared_floorplan_knob(project, pdk, "PL_TARGET_DENSITY")


def _flow_default_core_util(project: Path) -> Tuple[Optional[float], str]:
    """Read the pinned LibreLane floorplan default from this run's image.

    The image's `OpenROAD.Floorplan` variable is the only numeric source. An
    absent image record, unreadable container or malformed default is NOT_READ;
    this function never substitutes a flow constant for that missing evidence.
    """
    source = "pinned image: librelane.steps.openroad.Floorplan.FP_CORE_UTIL"
    try:
        rec = json.loads((project / "reports" / "container_image.json").read_text())
        container = str(rec.get("container") or "")
        if not container:
            return None, f"NOT_READ: {source}; container identity absent"
        code = ("from librelane.steps.openroad import Floorplan; "
                "print(next(v.default for v in Floorplan.config_vars "
                "if v.name == 'FP_CORE_UTIL'))")
        argv = ([sys.executable, "-c", code]
                if _cex.local_exec_mode("floorplan_knobs")
                else _cex.docker_exec_argv(container, "python3", "-c", code))
        run = subprocess.run(argv,
                             capture_output=True, text=True, timeout=60)
        if run.returncode != 0:
            return None, f"NOT_READ: {source}; container query failed"
        pct = float(run.stdout.strip())
        if not math.isfinite(pct) or not 0.0 < pct <= 100.0:
            return None, f"NOT_READ: {source}; invalid numeric default"
        return pct / 100.0, source
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired,
            _cex.ContainerImageMismatch):
        return None, f"NOT_READ: {source}; container query unreadable"
