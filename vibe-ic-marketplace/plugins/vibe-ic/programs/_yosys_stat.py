#!/usr/bin/env python3
"""_yosys_stat.py — parse a yosys ``stat`` design summary out of a synth log.

WHY THIS EXISTS
---------------
`flow/phase1_phase2_phase3.yaml` step 9 (Synthesis) declares

    phase2/stage2/synth/area.rpt OR phase2/stage2/synth/stats.json

as a required output.  A whole-tree grep on v1.7.36 found ZERO producers for
either path under ``phase2/stage2/synth`` — every ``area.rpt`` in the plugin is
the phase-3 OpenROAD one (``report_design_area > phase3/stage3/pnr/area.rpt``).
So the declared artefact was unproducible and, after #455 made
``required_outputs`` ALL-of-N, step 9 reports MISSING on every run no matter how
well synthesis went (measured on ~/campaign_pr427/spm/converge_ihp-sg13g2).

The measurement itself was never missing — both synth producers already run
yosys ``stat`` and both already keep the log.  It was simply never persisted in
a machine-readable form.  This module is the shared parser, so
`design_one_shot_runner.step_yosys_synth` (generic mapping) and
`phase3_one_shot_runner.step_synth` (liberty mapping) emit the SAME schema.

ANTI-FABRICATION CONTRACT
-------------------------
``parse_stat_block`` returns ``None`` when the log carries no yosys stat count
line at all.  Callers MUST NOT write ``stats.json`` in that case: a synth pass
whose stdout capture came back empty (the docker-fallback path can return rc=0
with nothing captured) has measured NOTHING, and a zeroed stats.json would flip
step 9 from an honest MISSING to a PASS on an unmeasured synthesis.  ``None``
means "no measurement", which is different from a measured zero.

``emit_stats_json`` extends the same contract to what is ALREADY on disk: a
pass that measured nothing also REMOVES the stats artefact this module wrote
earlier, because the netlist beside it has just been regenerated and the old
numbers now read as this pass's accounting for a design nobody measured.  It
removes only a file carrying this module's own schema.

IDENTITY BINDING
----------------
The payload records ``netlist_sha256`` — the digest of the netlist file the
numbers were measured on — alongside the ``netlist`` path.  A path is a NAME,
and two runs write different designs to the same name; the digest is what lets
a consumer ask "do these numbers describe THIS file?" and get an answer that a
re-run cannot fake.  It is also what tells a byte-identical ALIAS
(``netlist_yosys.v`` copied to ``netlist.v``) apart from a genuinely different
design, which a filename comparison cannot do.

FORMAT COVERAGE
---------------
yosys prints the ``stat`` summary in three interchangeable shapes depending on
build and on whether ``-liberty`` was passed:

    Number of cells:               446        (classic labelled form)
          446 cells                           (bare form, no liberty)
          349 5.84E+03 cells                  (liberty form: count + area col)

plus, with ``-liberty``, a design-area line:

       Chip area for module '\\spm': 5841.196200

All three count forms and the area line are parsed here.  chip-AGNOSTIC: pure
yosys-output-format parsing, no chip / PDK / vendor literal.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

# `=== <module> ===` section header that opens each per-module stat block.
_MODULE_RE = re.compile(r"^\s*===\s+(\S+)\s+===\s*$", re.M)
# `Number of cells:  NNNN`
_LABELLED_CELLS_RE = re.compile(r"^\s*Number of cells:\s*([0-9][0-9,]*)\s*$", re.M)
# `   NNNN cells` and the liberty `   NNNN 5.84E+03 cells` variant.
_BARE_CELLS_RE = re.compile(
    r"^\s*([0-9][0-9,]*)\s+(?:[0-9][0-9.eE+-]*\s+)?cells\s*$", re.M)
# `   Chip area for module '\top': 5841.196200`
_CHIP_AREA_RE = re.compile(
    r"^\s*Chip area for module\s+'\\?([^']+)':\s*([0-9][0-9.eE+-]*)\s*$", re.M)
# One histogram row: `   64 3.14E+03   sg13g2_dfrbpq_1` / `   64   $_DFF_P_`
_HISTOGRAM_RE = re.compile(
    r"^\s+([0-9][0-9,]*)\s+(?:[0-9][0-9.eE+-]*\s+)?"
    r"([\\$A-Za-z_][\w$\\.:\[\]-]*)\s*$")

# Stat metric rows that are NOT cell types (they share the histogram shape).
_NOT_A_CELL = frozenset({
    "wires", "bits", "ports", "cells", "memories", "processes",
})


def _to_int(raw: str) -> Optional[int]:
    try:
        return int(raw.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _last_module_name(text: str) -> Optional[str]:
    names = _MODULE_RE.findall(text)
    return names[-1] if names else None


def _cell_count(text: str) -> Tuple[Optional[int], Optional[str]]:
    """(count, which-form-matched). Prefers the labelled form; falls back to
    the bare / liberty-annotated form. Returns the LAST match — yosys prints
    the design-level summary last."""
    labelled = _LABELLED_CELLS_RE.findall(text)
    if labelled:
        return _to_int(labelled[-1]), "number_of_cells"
    bare = _BARE_CELLS_RE.findall(text)
    if bare:
        return _to_int(bare[-1]), "bare_cells_line"
    return None, None


def _histogram(text: str) -> Dict[str, int]:
    """Cell-type histogram from the LAST stat block. Only rows AFTER that
    block's `cells` summary line are considered, so the `wires` / `ports`
    metric rows above it cannot masquerade as cell types."""
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if _BARE_CELLS_RE.match(ln) or _LABELLED_CELLS_RE.match(ln):
            start = i + 1
    if start is None:
        return {}
    hist: Dict[str, int] = {}
    for ln in lines[start:]:
        if not ln.strip():
            break
        m = _HISTOGRAM_RE.match(ln)
        if not m:
            break
        name = m.group(2)
        if name.lower() in _NOT_A_CELL:
            continue
        n = _to_int(m.group(1))
        if n is not None:
            hist[name] = hist.get(name, 0) + n
    return hist


def _stat_block_tail(text: str, max_lines: int = 60) -> List[str]:
    """The tail of the LAST `=== <module> ===` section, verbatim, so a reviewer
    can check the parsed numbers against the tool's own words."""
    idx = None
    for m in _MODULE_RE.finditer(text):
        idx = m.start()
    if idx is None:
        return []
    return text[idx:].splitlines()[:max_lines]


def parse_stat_block(text: str) -> Optional[Dict[str, Any]]:
    """Parse the last yosys ``stat`` summary in ``text``.

    Returns ``None`` when no cell-count line is present at all (NO MEASUREMENT
    — the caller must not write a stats artefact). Otherwise a dict with:

        cells             int    — cell count from the tool's own stat line
        cells_source      str    — which stat line form was parsed
        top_module        str|None
        chip_area_um2     float|None  — only present with `stat -liberty`
        cell_histogram    {cell_type: count}
        stat_block        [str]  — verbatim tail of the parsed block
    """
    if not text:
        return None
    cells, source = _cell_count(text)
    if cells is None:
        return None
    out: Dict[str, Any] = {
        "cells": cells,
        "cells_source": source,
        "top_module": _last_module_name(text),
        "chip_area_um2": None,
        "cell_histogram": _histogram(text),
        "stat_block": _stat_block_tail(text),
    }
    areas = _CHIP_AREA_RE.findall(text)
    if areas:
        mod, val = areas[-1]
        try:
            out["chip_area_um2"] = float(val)
        except ValueError:
            out["chip_area_um2"] = None
        if out["top_module"] is None:
            out["top_module"] = mod
    return out


#: Field carrying the SHA-256 of the netlist these numbers were measured on.
#: The `netlist` field alone is a NAME, and a name cannot distinguish this
#: run's netlist from the previous run's netlist at the same path — which is
#: precisely the ghost-artefact shape #426 named one artefact upstream. The
#: digest is what makes "these numbers describe THAT file" a checkable claim
#: rather than a co-location assumption.
NETLIST_DIGEST_FIELD = "netlist_sha256"


def netlist_digest(path: Optional[Path]) -> Optional[str]:
    """``"sha256:<hex>"`` for ``path``, or ``None`` when it cannot be read.

    ``None`` is NOT a digest of an empty file: it records that the binding is
    unavailable, so a consumer states the gap instead of comparing against a
    fabricated constant.
    """
    if path is None:
        return None
    try:
        h = hashlib.sha256()
        with Path(path).open("rb") as fp:
            for chunk in iter(lambda: fp.read(65536), b""):
                h.update(chunk)
    except OSError:
        return None
    return "sha256:" + h.hexdigest()


def build_stats_payload(text: str, *, log_rel: str, netlist_rel: str,
                        tool: str, frontend: Optional[str] = None,
                        liberty: Optional[str] = None,
                        netlist_sha256: Optional[str] = None,
                        ) -> Optional[Dict[str, Any]]:
    """`parse_stat_block` + the provenance fields step 9 needs, or None.

    ``None`` propagates the anti-fabrication contract: no stat block parsed →
    no artefact written → step 9 stays honestly MISSING.

    ``netlist_sha256`` binds the numbers to the CONTENT of the netlist they
    describe. It is omitted rather than nulled when unavailable, so a consumer
    can tell "this artefact predates the binding" from "the binding says the
    netlist was unreadable"."""
    parsed = parse_stat_block(text)
    if parsed is None:
        return None
    payload: Dict[str, Any] = dict(parsed)
    payload["tool"] = tool
    payload["measured_from"] = log_rel
    payload["netlist"] = netlist_rel
    if netlist_sha256:
        payload[NETLIST_DIGEST_FIELD] = netlist_sha256
    if frontend:
        payload["synth_frontend"] = frontend
    if liberty:
        payload["liberty"] = liberty
    return payload


STATS_FILENAME = "stats.json"


def emit_stats_json(synth_dir: Path, text: str,
                    netlist_path: Optional[Path] = None,
                    **prov: Any) -> Optional[Path]:
    """Write ``<synth_dir>/stats.json`` from a yosys log capture, or nothing.

    Returns the path written, or ``None`` when the capture carried no yosys
    stat block (NO MEASUREMENT — step 9 must stay honestly MISSING rather than
    gain a fabricated zero) or when the write itself failed. Never raises: a
    report write must not turn a real synth PASS into a FAIL.

    Both synth producers (`design_one_shot_runner.step_yosys_synth` and
    `phase3_one_shot_runner.step_synth`) go through here so the two cannot
    drift into different schemas for the same declared artefact.

    NO MEASUREMENT REMOVES A PRIOR ARTEFACT, IT DOES NOT LEAVE IT STANDING.
    The anti-fabrication contract used to guarantee only that this call writes
    nothing. That is not enough on a re-run: the netlist at ``netlist_rel`` has
    just been regenerated, so the ``stats.json`` a PREVIOUS pass left beside it
    now reads as this pass's accounting for a design it never measured. Leaving
    it is the ghost-artefact shape, and it is worse than absence, because
    absence is something step 9's ``required_outputs`` reports out loud. The
    stale artefact is therefore removed and step 9 goes back to honestly
    MISSING. Only an artefact carrying this module's own schema is removed —
    an unparseable or foreign file is left exactly where it is, since deleting
    another writer's record was never this function's call to make.

    ``netlist_path`` is the file the numbers describe; its digest is recorded
    so a consumer can check the binding instead of trusting co-location. When
    it is not supplied the netlist is resolved as ``<synth_dir>/<basename of
    netlist_rel>``, which is where both producers put it.
    """
    payload = build_stats_payload(text, **prov)
    out = Path(synth_dir) / STATS_FILENAME
    if netlist_path is None:
        rel = str(prov.get("netlist_rel") or "")
        if rel:
            netlist_path = Path(synth_dir) / PurePosixPath(
                rel.replace("\\", "/")).name
    if payload is None:
        _remove_own_stale_stats(out, Path(synth_dir))
        return None
    digest = netlist_digest(netlist_path)
    if digest:
        payload[NETLIST_DIGEST_FIELD] = digest
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    except OSError:
        return None
    return out


def _remove_own_stale_stats(out: Path, synth_dir: Optional[Path] = None) -> None:
    """Delete a stats artefact THIS module wrote **when it has gone stale**.

    Scoped deliberately: the file must parse as JSON and carry the
    ``measured_from``/``netlist`` pair this module writes. Anything else —
    an unparseable file, or `synth_area_stats_emit`'s schema, or a report a
    human dropped there — is left alone, because "no measurement here" is not
    a licence to destroy someone else's record.

    A RECORD THAT STILL BINDS IS NOT A GHOST, AND IS KEPT. Removal used to be
    unconditional, and that traded the ghost-artefact false clean for a false
    ALARM one tier up. MEASURED on this module directly: pass 1 with a real
    yosys capture writes ``stats.json`` (digest recorded, ``cells: 7``); pass 2
    with an EMPTY capture — the documented docker-fallback shape, where
    ``rc=0`` comes back with no stdout — deleted that file even though the
    netlist beside it was byte-identical and the recorded ``netlist_sha256``
    still matched it. Step 9's ``required_outputs`` is ALL-of, so the step went
    PASS -> MISSING for a record that was still TRUE, and it is
    self-perpetuating: with host yosys absent every pass takes the same path
    and deletes it again, so the step never recovers.

    The test is therefore the same CONTENT binding the emitter writes, not the
    fact that a re-synthesis happened: the record is removed only when it can
    no longer be true of the tree it sits in — its netlist is gone, or that
    netlist's bytes no longer hash to the digest the record carries. A record
    with no digest at all (an older plugin version) is treated as unbindable
    and removed, which is the pre-existing behaviour for exactly that case.
    """
    try:
        if not out.is_file():
            return
        rec = json.loads(out.read_text(errors="replace"))
    except (OSError, ValueError):
        return
    if not isinstance(rec, dict):
        return
    if "measured_from" not in rec or "netlist" not in rec:
        return
    if synth_dir is not None and _record_still_binds(rec, synth_dir):
        return
    try:
        out.unlink()
    except OSError:
        pass


def _record_still_binds(rec: Dict[str, Any], synth_dir: Path) -> bool:
    """True when *rec*'s recorded digest still matches the netlist it names.

    The netlist is resolved the way both producers place it —
    ``<synth_dir>/<basename of the recorded netlist path>`` — so the check
    reads the same file the accounting describes.
    """
    recorded = str(rec.get(NETLIST_DIGEST_FIELD) or "").strip().lower()
    if not recorded:
        return False
    name = PurePosixPath(str(rec.get("netlist") or "").replace("\\", "/")).name
    if not name:
        return False
    return netlist_digest(Path(synth_dir) / name) == recorded
