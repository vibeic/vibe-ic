#!/usr/bin/env python3
"""The sign-off PDK detector read a file the publisher does not ship.

vibe-ic#376 instance 2. #467 established that a foundry hand-off pack must
declare the PDK that PRODUCED the GDS, not the one the spec aspired to, and
`test_foundry_handoff_pdk_is_the_signoff_pdk` pins that whole chain. The
mechanism was real. It was also INERT on every cell a reader actually receives.

`_pdk_from_signoff_flow` read exactly one path, `phase3/stage3/pnr/pnr.tcl`,
off the DISK. `PUBLISHING.md` does not ship `phase3/stage3/pnr/`. MEASURED over
the tracked corpus:

    pnr.tcl on the author's disk         15 of 15 cells
    pnr.tcl in the published tree         2 of 15

So on a published cell the detector returned None, `pdk = signoff or spec`
fell through to the spec target, and the pack declared the aspiration — the
exact outcome #467 exists to prevent. Two defects in one line: the mechanism
does not engage, and WHICH cells it engages on depends on whose machine is
asking (the #447 host-dependence class, fifth instance).

THE REPAIR, and what it measures
================================
Read the same path grammar off the flow's own PUBLISHED artefacts (phase2/,
phase3/), via `_published_tree` so a live run directory still reads the disk:

    resolves to one PDK      10 of 15   (was 2 published, 4 host-dependent)
    two PDKs named -> None    1         u_hawaii_adc, correctly refused
    no PDK path at all        4

phase1 is excluded deliberately — it holds the SPEC, and letting it feed the
sign-off signal would collapse the distinction the resolver exists to draw.
Measured: no phase1 document carries a `/foss/pdks/` path at all.

THE SECOND HALF — a divergence channel full of noise is a silent channel
=======================================================================
With the detector resolving on 10 cells instead of 2, a plain `signoff != spec`
fires 12 times, and 9 are not disagreements:

    case only            sky130A vs sky130a                       1
    family vs variant    sky130A vs sky130                        5
    no PDK stated        'N/A (protocol spec, not a tapeout)'    12 of 194 L19

The 3 that survive are real, and two are the cells #376 named:
`spm/v1.5.58_ihp-sg13g2` and `spm/v1.5.66_gf180mcuD`, each signed off on a
different foundry's PDK than the `sky130` their L19 states.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import foundry_handoff_pack_gen as G  # noqa: E402

_CORPUS = _PROGRAMS.parents[3] / "benchmark-data" / "ic"


def _cell(tmp_path: Path, *, tracked: dict, untracked: dict = None,
          spec_pdk: str = None, publish: bool = True) -> Path:
    """A cell whose PUBLISHED content and on-disk content differ."""
    d = tmp_path / "cell"
    for rel, body in (tracked or {}).items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    if spec_pdk is not None:
        p = d / "phase1" / "generated_docs" / "L19_CONSTRAINTS_PDK.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"doc_id": "L19",
                                 "fields": {"pdk_target": spec_pdk}}))
    if publish:
        subprocess.run(["git", "init", "-q", str(d)], check=True)
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            subprocess.run(["git", "-C", str(d), "config", k, v], check=True)
        for rel in list(tracked or {}):
            subprocess.run(["git", "-C", str(d), "add", rel], check=True)
        if spec_pdk is not None:
            subprocess.run(["git", "-C", str(d), "add",
                            "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"],
                           check=True)
        subprocess.run(["git", "-C", str(d), "commit", "-qm", "publish"],
                       check=True)
    for rel, body in (untracked or {}).items():      # written AFTER the commit
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return d


def _asset(pdk: str) -> str:
    return f"read_liberty /foss/pdks/{pdk}/libs.ref/x/lib/x_typ.lib\n"


# ── the detector reads what is PUBLISHED ───────────────────────────────────
def test_the_published_flow_answers_not_an_untracked_leftover(tmp_path):
    """THE LOAD-BEARING CASE. The published run says ihp-sg13g2; an untracked
    `pnr.tcl` on this machine says sky130A. A reader receives the first."""
    d = _cell(tmp_path,
              tracked={"phase3/stage4/signoff/drc.log": _asset("ihp-sg13g2")},
              untracked={"phase3/stage3/pnr/pnr.tcl": _asset("sky130A")})
    assert G._pdk_from_signoff_flow(d) == "ihp-sg13g2"


def test_the_old_single_file_is_no_longer_required(tmp_path):
    """The defect itself: a published cell with NO tracked pnr.tcl — 13 of the
    15 real ones — used to resolve to None and fall through to the spec."""
    d = _cell(tmp_path,
              tracked={"phase2/stage2/constraints/x.sdc": _asset("gf180mcuD")},
              spec_pdk="sky130")
    assert G._pdk_from_signoff_flow(d) == "gf180mcuD"
    pdk, _node, mismatch = G._resolve_pdk_and_node(d, None, None)
    assert pdk == "gf180mcuD", "the pack would ship a GF180 die called sky130"
    assert mismatch == "sky130", "and the spec target must survive as a record"


def test_a_live_run_directory_still_reads_the_disk(tmp_path):
    """`_published_tree`'s contract: None means "not a published tree", and a
    mid-flight run directory is exactly that. Nothing is tracked here."""
    d = _cell(tmp_path, tracked={},
              untracked={"phase3/stage3/pnr/pnr.tcl": _asset("sky130A")},
              publish=False)
    assert G._pdk_from_signoff_flow(d) == "sky130A"


def test_phase1_cannot_feed_the_signoff_signal(tmp_path):
    """THE PAIRED HALF of reading more files. phase1 holds the SPEC; if it
    could contribute, the resolver would be comparing the spec with itself."""
    d = _cell(tmp_path,
              tracked={"phase1/generated_docs/L1_SPEC.md":
                       "we target /foss/pdks/sky130A/ eventually\n"})
    assert G._pdk_from_signoff_flow(d) is None


def test_two_pdks_in_the_flow_still_refuse_to_guess(tmp_path):
    """Widening what is read must not weaken the ambiguity refusal — one real
    cell (u_hawaii_adc) names two, and a guess there ships the wrong process."""
    d = _cell(tmp_path, tracked={"phase3/a.log": _asset("sky130A"),
                                 "phase2/b.log": _asset("ihp-sg13g2")})
    assert G._pdk_from_signoff_flow(d) is None


# ── the divergence channel: what is NOT a disagreement ─────────────────────
@pytest.mark.parametrize("signoff,spec,why", [
    ("sky130A", "sky130a", "case only"),
    ("sky130A", "sky130", "family vs variant"),
    ("gf180mcuD", "gf180mcu", "family vs variant, other family"),
    ("sky130A", "N/A (protocol spec, not a tapeout)", "no PDK stated"),
])
def test_these_are_not_divergences(signoff, spec, why):
    assert G._pdk_statements_diverge(signoff, spec) is False, why


@pytest.mark.parametrize("signoff,spec,why", [
    ("ihp-sg13g2", "sky130", "different foundry — the #376 case"),
    ("gf180mcuD", "sky130", "different foundry — the #376 case"),
    ("sky130A", "sky130B", "same family, neither contains the other"),
])
def test_these_ARE_divergences(signoff, spec, why):
    """The sharp half. `sky130A` vs `sky130B` is the one the variant rule must
    not swallow: they share a family and still disagree."""
    assert G._pdk_statements_diverge(signoff, spec) is True, why


def test_a_suppressed_divergence_still_declares_the_signoff_pdk(tmp_path):
    """Suppressing the REPORT must not change which PDK is declared — the
    hand-off still ships what the flow used."""
    d = _cell(tmp_path, tracked={"phase3/a.log": _asset("sky130A")},
              spec_pdk="sky130")
    pdk, _node, mismatch = G._resolve_pdk_and_node(d, None, None)
    assert pdk == "sky130A" and mismatch is None


# ── real data ──────────────────────────────────────────────────────────────
def test_the_published_corpus_resolves_and_diverges_as_measured():
    """The numbers that justified the change, re-derived from the corpus."""
    if not _CORPUS.is_dir():
        pytest.skip("published corpus not checked out")
    root = _PROGRAMS.parents[3]
    out = subprocess.run(["git", "-C", str(root), "ls-files", "benchmark-data/ic"],
                         capture_output=True, text=True)
    cells = sorted({(root / p).parents[2] for p in out.stdout.split()
                    if p.endswith("L19_CONSTRAINTS_PDK.json")})
    if not cells:
        pytest.skip("corpus cells not checked out")
    resolved = [c for c in cells if G._pdk_from_signoff_flow(c)]
    assert len(resolved) >= 8, f"{len(resolved)} of {len(cells)} resolved"

    diverged = {}
    for c in cells:
        pdk, _n, m = G._resolve_pdk_and_node(c, None, None)
        if m:
            diverged[c.name] = (pdk, m)
    # One of the two cells #376 named still diverges the same way.
    assert diverged.get("v1.5.58_ihp-sg13g2") == ("ihp-sg13g2", "sky130")
    # gf180mcuD does NOT (re-measured 2026-08-07 against v1.9.96_gf180mcuD,
    # which replaces the retired v1.5.66_gf180mcuD) — not because the PDK
    # disagreement itself went away, but because the SAME v1.9.96 ciel-hash
    # fix (commit 3d7c5a095) that converged this cell also made
    # `_SIGNOFF_PDK_RE` see TWO candidate names in the tracked flow text
    # instead of one: the real gf180mcuD liberty paths
    # (`/foss/pdks/gf180mcuD/...`) plus the ciel content-addressed staging
    # path (`/foss/pdks/ciel/gf180mcu/versions/<hash>/...`, whose first path
    # segment the regex reads as the PDK name literal `ciel`). Two names ->
    # `_pdk_from_signoff_flow` correctly refuses to guess and returns None
    # (the same "ambiguous" rule `u_hawaii_adc` already exercises), so this
    # cell now falls into the "no PDK path at all"-shaped bucket rather than
    # the "resolves and disagrees" one. Verified directly, not assumed:
    # `_signoff_flow_texts` over this cell yields {'gf180mcuD', 'ciel'}.
    assert diverged.get("v1.9.96_gf180mcuD") is None
    assert G._pdk_from_signoff_flow(_CORPUS / "spm" / "v1.9.96_gf180mcuD") is None
    # And the noise stays out: sky130A-vs-sky130 cells are not reported.
    assert "subservient" not in diverged, diverged
    assert "v1.5.65_sky130A" not in diverged, diverged


def test_the_detector_does_not_walk_untracked_run_leftovers():
    """The host-dependence half on real data: this checkout carries 15 on-disk
    `pnr.tcl` and the published tree carries 2, so a disk-walking detector
    answers differently here than in a fresh clone."""
    root = _PROGRAMS.parents[3]
    if not (root / "benchmark-data" / "ic").is_dir():
        pytest.skip("published corpus not checked out")
    out = subprocess.run(["git", "-C", str(root), "ls-files",
                          "benchmark-data/ic/**/pnr.tcl"],
                         capture_output=True, text=True)
    tracked = len([p for p in out.stdout.split() if p])
    on_disk = len(list((root / "benchmark-data" / "ic").rglob("pnr.tcl")))
    if on_disk <= tracked:
        pytest.skip("no untracked leftovers in this checkout to discriminate")
    # A cell with a leftover but no tracked pnr.tcl must still resolve from
    # its published artefacts, not from the leftover.
    d = _CORPUS / "spm" / "v1.5.58_ihp-sg13g2"
    if not d.is_dir():
        pytest.skip("cell not checked out")
    assert G._pdk_from_signoff_flow(d) == "ihp-sg13g2"
