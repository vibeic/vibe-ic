#!/usr/bin/env python3
"""
l8_clock_domains_typed_check.py — Wave 38 / B4

Audit-driven typed sub-field depth gate. Multi-clock designs need
the clock-domain map (master clock + derived/divided clocks) as a
typed structure for spec-to-rtl, sdc-validator and CDC checking.
PHASE2A_FULL_AUDIT_v0119.67 noted vendor docs declare master /
derived clocks but L8 only carries the bit-decoder threshold ticks.

Trigger: extracted vendor docs OR L8.* contain >=2 distinct
frequency mentions (regex ``\\d+\\.?\\d*\\s*(MHz|kHz|GHz|Hz)``)
indicating a multi-clock topology. Canonical CDC evidence that resolves at
least two roots, corroborated by L9 input ports or active SDC clock commands,
also triggers the gate. A disagreement is the named blocking finding
``EXTRACTION_APPLICABILITY_CONTRADICTION`` and can never take the SKIP path.

Required typed shape: L8 (or L9 / L8 ``timing_constants``) MUST
have a ``clock_domains`` array (or ``clocks`` / ``clock_map`` /
``clock_topology``). Each entry MUST carry:
  - ``name`` (string)
  - ``freq_hz`` or ``freq_mhz`` or ``period_ns`` (one of)
  - ``role`` (one of master/system/core/derived/external)
    OR ``source`` (string parent / external)
  - optional ``divider`` for derived clocks.

The gate is chip-AGNOSTIC: only the schema depth is enforced, not
particular frequencies.

Usage:
    python3 l8_clock_domains_typed_check.py <project_dir>

Exit codes:
    0 = PASS (typed clock_domains present)
    1 = FAIL (multi-clock topology detected but no typed clocks[])
    2 = input-missing (skip)

Honors waiver ``l8_clock_domains_intentional_simplification`` (>=40
chars).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _path_layout as _pl  # noqa: E402
from ic_class_profile import detect_ic_class  # noqa: E402


# Wave 43 (v0.119.75) — explicit ic_class_profile guard.
# Typed clock-domain map is required when the IC carries multiple
# fab-side clock domains (digital cmd-driven, AID-class, mixed
# signal). Bare-FPGA scaffolds usually run on a single eval-board
# clock and rely on the QSF/SDC, not L8.
_SKIP_CLASSES = ("bare_fpga",)


_DOC_GLOBS = (
    "**/input_doc/*.txt",
    "**/input/docs/*.txt",
)

_L8_GLOBS = (
    "phase1/generated_docs/L8_TIMING_WAVEFORM.json",
    "phase1/generated_docs/L8_RTL_CONSTANTS.json",
    "phase1/generated_docs/L8*.json",
)

_L9_GLOBS = (
    "phase1/generated_docs/L9_INTEGRATION_SPEC.json",
)

_CDC_GLOBS = (
    "reports/phase2/cdc/crossing.json",
    "reports/phase2/cdc/async_input.json",
    "reports/phase2/cdc/reset_dep.json",
)

_PORT_LIST_KEYS = ("top_ports", "ports", "top_module_pins")

_RE_FREQ = re.compile(r"(\d+\.?\d*)\s*(MHz|kHz|GHz|Hz)\b", re.IGNORECASE)

# v1.6.89 (#21 Bug 2 P0) — gate-side context-window + sub-kHz filter.
# Mirrors _is_real_clock_freq from phase1_one_shot_runner so the gate
# does NOT count "respond within 2 Hz of nominal" / "tolerance 5 Hz" /
# similar non-clock prose hits as distinct frequency mentions. Without
# this, the gate triggers `len(distinct) >= 2` on tolerance prose +
# the actual clock and demands a typed clock_domains[] on truly
# single-clock designs. Chip-AGNOSTIC.
_CLOCK_KEYWORD_RE = re.compile(
    r"\b(?:clk|clock|oscillator|osc|xtal|crystal|freq|frequency|"
    r"periodic|tick|reference)\b",
    re.IGNORECASE,
)


def _resolve_freq_to_hz(value_str: str, unit: str) -> float:
    """Convert (value_str, unit) → Hz float. Lower-case unit."""
    try:
        v = float(value_str)
    except (TypeError, ValueError):
        return 0.0
    u = (unit or "").lower()
    if u == "ghz":
        return v * 1.0e9
    if u == "mhz":
        return v * 1.0e6
    if u == "khz":
        return v * 1.0e3
    return v  # Hz


def _is_real_clock_freq(text: str, freq_hz: float,
                        span_start: int, span_end: int,
                        char_window: int = 50) -> bool:
    """v1.6.89 (#21 Bug 2 P0) — sub-kHz reject + ±char_window
    clock-keyword context check. Returns True only when the literal
    is plausibly a real clock frequency mention.

    Mirror of phase1_one_shot_runner._is_real_clock_freq so the
    gate's _scan_freq_mentions filters parser garbage the same way
    the ingest path does. Without this, v1.6.88's #20 Bug 1 fix is
    only half-applied (ingest-side only) and the gate still trips
    on tolerance numbers. Chip-AGNOSTIC."""
    if freq_hz < 1000.0:
        return False
    window_start = max(0, span_start - char_window)
    window_end = min(len(text), span_end + char_window)
    window = text[window_start:window_end]
    if not _CLOCK_KEYWORD_RE.search(window):
        return False
    return True


_CLOCK_KEYS = ("clock_domains", "clocks", "clock_map", "clock_topology",
               "clock_bindings", "clock_binding", "clock_table")

_REQUIRED_NAME_KEYS = ("name", "clock", "clk")
_REQUIRED_FREQ_KEYS = ("freq_hz", "freq_mhz", "frequency", "period_ns",
                        "freq", "rate_hz", "rate_mhz")
_REQUIRED_ROLE_KEYS = ("role", "source", "type", "kind", "parent")


def _find_first(project: Path, globs) -> Optional[Path]:
    for pat in globs:
        for hit in project.glob(pat):
            if hit.is_file():
                return hit
    return None


def _scan_freq_mentions(project: Path) -> Set[str]:
    """v1.6.89 (#21 Bug 2 P0) — gate-side filter mirrors the ingest-
    side _is_real_clock_freq from phase1_one_shot_runner. Sub-kHz
    hits and hits without a clock-keyword token in a ±50-char window
    are rejected before counting toward the multi-clock-topology
    threshold. Chip-AGNOSTIC."""
    distinct: Set[str] = set()
    seen = set()
    for pat in _DOC_GLOBS:
        for doc in project.glob(pat):
            if not doc.is_file() or doc in seen:
                continue
            seen.add(doc)
            try:
                text = doc.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for m in _RE_FREQ.finditer(text):
                val, unit = m.group(1), m.group(2).lower()
                freq_hz = _resolve_freq_to_hz(val, unit)
                if not _is_real_clock_freq(text, freq_hz,
                                            m.start(), m.end()):
                    continue
                distinct.add(f"{val}{unit}")
                if len(distinct) >= 20:
                    return distinct
    return distinct


def _rel(project: Path, path: Path) -> str:
    try:
        return path.relative_to(project).as_posix()
    except ValueError:
        return str(path)


def _collect_named_list(node, key: str, out: Set[str]) -> None:
    """Collect normalized string members below every exact *key*."""
    if isinstance(node, dict):
        for item_key, value in node.items():
            if item_key == key and isinstance(value, list):
                out.update(str(item).strip().lower() for item in value
                           if isinstance(item, str) and item.strip())
            else:
                _collect_named_list(value, key, out)
    elif isinstance(node, list):
        for value in node:
            _collect_named_list(value, key, out)


def _resolved_clock_roots(project: Path) -> Tuple[Set[str], List[str]]:
    """Read canonical structured CDC root evidence and cite its sources."""
    roots: Set[str] = set()
    sources: List[str] = []
    for relpath in _CDC_GLOBS:
        path = project / relpath
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8",
                                             errors="replace"))
        except Exception:
            continue
        before = len(roots)
        _collect_named_list(data, "clocks_found", roots)
        if len(roots) > before:
            sources.append(f"{_rel(project, path)}:clocks_found")
    return roots, sources


def _l9_input_ports(project: Path) -> Tuple[Set[str], List[str]]:
    """Read structured L9 top/input port names, without name heuristics."""
    names: Set[str] = set()
    sources: List[str] = []
    for pattern in _L9_GLOBS:
        for path in sorted(project.glob(pattern)):
            if not path.is_file():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8",
                                                 errors="replace"))
            except Exception:
                continue
            found: Set[str] = set()

            def visit(node) -> None:
                if isinstance(node, dict):
                    for key, value in node.items():
                        if key in _PORT_LIST_KEYS and isinstance(value, list):
                            for entry in value:
                                if not isinstance(entry, dict):
                                    continue
                                direction = str(entry.get("direction") or
                                                entry.get("mode") or "").lower()
                                if direction and direction not in {"input", "in"}:
                                    continue
                                name = entry.get("name") or entry.get("port")
                                if isinstance(name, str) and name.strip():
                                    found.add(name.strip().lower())
                        else:
                            visit(value)
                elif isinstance(node, list):
                    for value in node:
                        visit(value)

            visit(data)
            if found:
                names.update(found)
                sources.append(f"{_rel(project, path)}:input_ports")
    return names, sources


_SDC_CLOCK_CMD_RE = re.compile(r"\bcreate_(?:generated_)?clock\b", re.I)
_SDC_NAME_RE = re.compile(r"(?:^|\s)-name\s+\{?([^\s}\]]+)", re.I)
_SDC_TARGET_RE = re.compile(
    r"\[\s*get_(?:ports|pins)\s+\{?([^\s}\]]+)", re.I)


def _sdc_clock_names(project: Path) -> Tuple[Set[str], List[str]]:
    """Read clock names/targets from active create-clock SDC commands."""
    names: Set[str] = set()
    sources: List[str] = []
    for path in _pl.clock_plan_input_sdcs(project):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        # Tcl line continuations become spaces; comments remain line-scoped.
        active = "\n".join(line.split("#", 1)[0]
                           for line in text.replace("\\\n", " ").splitlines())
        found: Set[str] = set()
        for command in re.split(r"[;\n]", active):
            if not _SDC_CLOCK_CMD_RE.search(command):
                continue
            found.update(m.group(1).strip().lower()
                         for m in _SDC_NAME_RE.finditer(command))
            found.update(m.group(1).strip().lower()
                         for m in _SDC_TARGET_RE.finditer(command))
        if found:
            names.update(found)
            sources.append(f"{_rel(project, path)}:create_clock")
    return names, sources


def _resolved_multiclock_evidence(
        project: Path, distinct_freqs: Set[str],
        entries: List[dict]) -> Optional[Dict[str, Any]]:
    """Return independent multi-clock evidence and L-doc declaration depth."""
    if len(distinct_freqs) >= 2:
        return None
    roots, cdc_sources = _resolved_clock_roots(project)
    ports, port_sources = _l9_input_ports(project)
    sdc_names, sdc_sources = _sdc_clock_names(project)
    corroborated = roots & (ports | sdc_names)
    if len(roots) < 2 or len(corroborated) < 2:
        return None
    clock_map_names = sorted({name for name in
                              (_canonical_clock_name(entry)
                               for entry in entries) if name is not None})
    return {
        "frequency_mentions": sorted(distinct_freqs),
        "clock_map_names": clock_map_names,
        "resolved_roots": sorted(roots),
        "corroborated_roots": sorted(corroborated),
        "cdc_sources": cdc_sources,
        "port_sdc_sources": port_sources + sdc_sources,
    }


def _collect_clock_entries(node, out: List[dict]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k in _CLOCK_KEYS:
                if isinstance(v, list):
                    for it in v:
                        if isinstance(it, dict):
                            out.append(it)
                elif isinstance(v, dict):
                    # dict-of-clocks form: {name: {...}}
                    for cname, cval in v.items():
                        if isinstance(cval, dict):
                            entry = dict(cval)
                            entry.setdefault("name", cname)
                            out.append(entry)
            else:
                _collect_clock_entries(v, out)
    elif isinstance(node, list):
        for it in node:
            _collect_clock_entries(it, out)


def _entry_typed_ok(entry: dict) -> List[str]:
    missing = []
    if not any(k in entry for k in _REQUIRED_NAME_KEYS):
        missing.append("name")
    if not any(k in entry for k in _REQUIRED_FREQ_KEYS):
        missing.append("freq_hz/freq_mhz/period_ns")
    if not any(k in entry for k in _REQUIRED_ROLE_KEYS):
        missing.append("role/source")
    return missing


def _canonical_clock_name(entry: dict) -> Optional[str]:
    """ORGANIC-20260531 — extract a clock's canonical name from an
    entry using _REQUIRED_NAME_KEYS, case-normalized. Returns None
    when no name field is present or it is blank. chip-AGNOSTIC."""
    if not isinstance(entry, dict):
        return None
    for k in _REQUIRED_NAME_KEYS:
        v = entry.get(k)
        if isinstance(v, str):
            norm = v.strip().lower()
            if norm:
                return norm
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: l8_clock_domains_typed_check <project_dir>",
              file=sys.stderr)
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        return 2

    entries: List[dict] = []
    for globs in (_L8_GLOBS, _L9_GLOBS):
        for pat in globs:
            for hit in project.glob(pat):
                if hit.is_file():
                    try:
                        data = json.loads(hit.read_text())
                    except Exception:
                        continue
                    _collect_clock_entries(data, entries)

    distinct_freqs = _scan_freq_mentions(project)
    resolved_multi = _resolved_multiclock_evidence(
        project, distinct_freqs, entries)
    if resolved_multi is not None and len(resolved_multi["clock_map_names"]) < 2:
        cdc_sources = resolved_multi["cdc_sources"]
        corroborating = resolved_multi["port_sdc_sources"]
        cdc_path = cdc_sources[0].split(":", 1)[0]
        corroborating_path, corroborating_kind = corroborating[0].split(":", 1)
        print("[FAIL] l8_clock_domains_typed_check: "
              "BLOCKING EXTRACTION_APPLICABILITY_CONTRADICTION: "
              f"input-doc:freq={len(distinct_freqs)} vs "
              f"{cdc_path}:roots={len(resolved_multi['resolved_roots'])}; "
              f"{Path(corroborating_path).name}:"
              f"{corroborating_kind} corroborate")
        print("  frequency_mentions="
              f"{resolved_multi['frequency_mentions']!r}")
        print(f"  clock_map_names={resolved_multi['clock_map_names']!r}")
        print(f"  resolved_roots={resolved_multi['resolved_roots']!r}")
        print(f"  corroborated_roots={resolved_multi['corroborated_roots']!r}")
        print(f"  CDC sources={cdc_sources!r}")
        print(f"  port/SDC sources={corroborating!r}")
        return 1

    profile = detect_ic_class(project)
    ic_class = profile.get("ic_class", "unknown")
    if ic_class in _SKIP_CLASSES:
        print(f"[SKIP] l8_clock_domains_typed_check: "
              f"ic_class={ic_class} (FPGA evaluation board uses a "
              f"single eval-board clock; L8 clock_domains[] not "
              f"applicable)")
        return 2

    if len(distinct_freqs) < 2 and resolved_multi is None:
        print("[SKIP] l8_clock_domains_typed_check: "
              f"single-clock topology (only {len(distinct_freqs)} "
              "distinct freq mention)")
        return 2

    if not entries:
        print(f"[FAIL] l8_clock_domains_typed_check: "
              f"{len(distinct_freqs)} distinct frequencies "
              f"({sorted(distinct_freqs)[:6]}) suggest multi-clock "
              f"topology but neither L8 nor L9 declares a typed "
              f"clock_domains[] / clocks[] array.")
        return 1

    # ORGANIC-20260531 — evaluate typed-ness PER CLOCK NAME, not per
    # raw entry. The same physical clock can legitimately appear in
    # more than one L doc: fully typed in L8.clock_domains and again
    # as a bare structural mirror in L9.clocks (name + edge only) so
    # STA / CDC have a port handle. Pre-compute the set of clock names
    # that are fully typed by SOME entry, then suppress a shallow
    # finding only when a same-named typed sibling exists. Purely
    # additive: every entry the per-entry loop accepted is still
    # accepted, and a clock that NO entry ever fully types stays
    # flagged. chip-AGNOSTIC: key on the clock name only.
    typed_names: Set[str] = set()
    for e in entries:
        if not _entry_typed_ok(e):
            cname = _canonical_clock_name(e)
            if cname is not None:
                typed_names.add(cname)

    bad: List[str] = []
    for i, e in enumerate(entries):
        missing = _entry_typed_ok(e)
        if not missing:
            continue
        cname = _canonical_clock_name(e)
        if cname is not None and cname in typed_names:
            # A same-named sibling fully types this clock; the bare
            # mirror here is structurally fine — suppress.
            continue
        label = (e.get("name") or e.get("clock")
                 or f"clock[{i}]")
        bad.append(f"{label}: missing {','.join(missing)}")

    if bad:
        print(f"[FAIL] l8_clock_domains_typed_check: "
              f"{len(bad)}/{len(entries)} clock entries too shallow. "
              f"Examples: {'; '.join(bad[:5])}")
        return 1

    print(f"[PASS] l8_clock_domains_typed_check: "
          f"{len(entries)} typed clock domain entries with "
          f"name/freq/role")
    return 0


if __name__ == "__main__":
    sys.exit(main())
