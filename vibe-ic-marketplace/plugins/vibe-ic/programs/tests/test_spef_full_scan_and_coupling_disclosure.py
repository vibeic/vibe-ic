#!/usr/bin/env python3
"""Step 22 — the SPEF substance check that could not see the SPEF.

THE READ WINDOW. `spef_extraction_check.audit()` ran its substance checks
against `sf.read_text()[:8192]`. A SPEF's first 8 KB is header + name map +
port list; `*D_NET` records start after it on any real design, so the one
question the gate asks about net content was answered from a region that
structurally cannot contain the answer.

MEASURED on the real completed run `campaign_pr427/spm/converge_ihp-sg13g2`
(pure-digital standard-cell; this step's artefact is digital):

    ground truth   grep -c '^*D_NET' spm.spef      -> 460
                   grep -bo '*D_NET' | head -1     -> byte 50386
    origin/main    summary.has_nets = false, WARNING NO_NETS, rc 0
    this branch    summary.has_nets = true, d_nets = 460, rc 0

THE COUPLING DISCLOSURE. Step 27 (Signal Integrity) `blocks_on: [22]`, but
step 22's gate never looked at whether the extraction carried lateral coupling
capacitance. On that same real run every one of the 2040 `*CAP` entries is a
3-field grounded cap and there are zero 4-field coupling entries — which is why
`si_crosstalk.json` says "No SPEF coupling caps available for this run" and
`si_mcf_sta_check` reports `coupling_pairs: 0`, while step 22 returned PASS.

    origin/main    findings = [WARNING NO_NETS]              (and it was wrong)
    this branch    findings = [WARNING NO_COUPLING_CAPS]     (and it is right)

WHAT IT COSTS. Nothing in rc: both findings are WARNING, the gate's exit code
is 0 before and after on the real run. It costs one full read of each SPEF
instead of 8 KB (streaming, one pass) and it makes an honest tier-1 extraction
say so out loud. The disclosure is deliberately NOT blocking — a grounded-cap
extraction is step 22's own declared tier 1, a legitimate result; what was
wrong was that it was invisible.

DIRECTION-1 GUARDS (`test_d1_*`) hold on the pre-fix tree too.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "spef_extraction_check.py"
sys.path.insert(0, str(_PROGRAMS))

_HEADER = (
    '*SPEF "ieee 1481-1999"\n'
    '*DESIGN "spm"\n'
    '*DATE "16:46:35 Sunday July 26, 2026"\n'
    '*VENDOR "The OpenROAD Project"\n'
    '*PROGRAM "OpenROAD"\n'
    "*DIVIDER /\n*DELIMITER :\n*BUS_DELIMITER []\n"
    "*T_UNIT 1 NS\n*C_UNIT 1 PF\n*R_UNIT 1 OHM\n*L_UNIT 1 HENRY\n\n"
)


def _name_map(n: int) -> str:
    """The real spm.spef's name map is ~50 KB — it is what pushes the first
    *D_NET past the 8 KB read window. Reproduce that shape, not a stub."""
    return "*NAME_MAP\n" + "".join(
        f"*{39 + i} _some_rather_long_internal_net_name_{i:05d}_\n"
        for i in range(n)) + "\n"


def _d_net(idx: int, coupling: bool) -> str:
    """One OpenROAD *D_NET record, verbatim in shape (see the real file).

    A *CAP entry is `idx node value` (grounded) or `idx node1 node2 value`
    (coupling) — the field count is the only difference.
    """
    cap = (f"1 *{idx}:D 2.96094e-05\n"
           f"2 *{idx}:Y 0.000193369\n"
           f"3 *{idx}:8 0.000222979\n")
    if coupling:
        cap += f"4 *{idx}:8 *{idx + 1}:8 1.23e-05\n"
    return (f"*D_NET *{idx} 0.000445958\n"
            f"*CONN\n"
            f"*I *{idx}:D I *D sg13g2_dfrbpq_1\n"
            f"*I *{idx}:Y O *D sg13g2_nor2_1\n"
            f"*CAP\n{cap}"
            f"*RES\n1 *{idx}:Y *{idx}:8 41.8334\n"
            f"*END\n\n")


def _spef(nets: int = 460, coupling: bool = False, map_entries: int = 1200) -> str:
    return (_HEADER + _name_map(map_entries)
            + "".join(_d_net(39 + i, coupling) for i in range(nets)))


def _project(tmp: Path, text: str) -> Path:
    ext = tmp / "phase3" / "stage3" / "extracted"
    ext.mkdir(parents=True, exist_ok=True)
    (ext / "spm.spef").write_text(text)
    return tmp


def _run(proj: Path):
    out = proj / "out.json"
    r = subprocess.run([sys.executable, str(_PROG), str(proj),
                        "--json", str(out)],
                       capture_output=True, text=True, timeout=120)
    return r, json.loads(out.read_text())


def _categories(doc):
    return [f["category"] for f in doc["findings"]]


# ===========================================================================
# The whole file is read
# ===========================================================================
def test_nets_past_the_first_8kb_are_seen(tmp_path):
    """The real-run shape: 460 *D_NET records, the first one past byte 8192."""
    text = _spef(nets=460)
    proj = _project(tmp_path, text)
    assert text.index("*D_NET") > 8192, (
        "fixture does not reproduce the defect: the first *D_NET is inside "
        "the old 8 KB window")
    r, doc = _run(proj)
    assert doc["summary"]["has_nets"] is True, (
        "the checker is still blind past its read window")
    assert "NO_NETS" not in _categories(doc)
    assert r.returncode == 0


def test_the_net_count_matches_the_file(tmp_path):
    """Not just "some nets" — the reported count must be the real one, which
    is what makes the summary usable as evidence."""
    proj = _project(tmp_path, _spef(nets=460))
    _, doc = _run(proj)
    assert doc["summary"]["d_nets"] == 460, doc["summary"]


def test_a_truly_netless_spef_still_warns(tmp_path):
    """The two-sided control: reading the whole file must not turn NO_NETS
    into something that can never fire."""
    proj = _project(tmp_path, _HEADER + _name_map(1200))
    _, doc = _run(proj)
    assert doc["summary"]["has_nets"] is False
    assert "NO_NETS" in _categories(doc)


def test_a_net_named_only_inside_a_comment_is_not_a_net(tmp_path):
    """A mention is not a record. The old substring test counted a commented
    `*D_NET` as evidence of extraction."""
    text = _HEADER + _name_map(1200) + "// *D_NET *39 0.0004  (commented out)\n"
    proj = _project(tmp_path, text)
    _, doc = _run(proj)
    assert doc["summary"]["has_nets"] is False, doc["summary"]
    assert doc["summary"]["d_nets"] == 0


# ===========================================================================
# The coupling-tier disclosure
# ===========================================================================
def test_grounded_cap_only_extraction_is_disclosed(tmp_path):
    """The real run's shape: 2040 grounded caps, zero coupling caps, and step
    27 downstream reporting a clean SI PASS off it."""
    proj = _project(tmp_path, _spef(nets=460, coupling=False))
    r, doc = _run(proj)
    assert doc["summary"]["coupling_caps"] == 0
    assert doc["summary"]["ground_caps"] == 460 * 3
    assert "NO_COUPLING_CAPS" in _categories(doc), (
        "an extraction with no lateral Cc at all is not disclosed anywhere "
        "upstream of the SI step that blocks_on it")
    assert r.returncode == 0, "the disclosure must stay advisory"


def test_a_coupled_extraction_is_not_falsely_flagged(tmp_path):
    """The two-sided control on the disclosure. A tier-2/3 extraction carrying
    real coupling caps must NOT be told it has none."""
    proj = _project(tmp_path, _spef(nets=460, coupling=True))
    r, doc = _run(proj)
    assert doc["summary"]["coupling_caps"] == 460, doc["summary"]
    assert "NO_COUPLING_CAPS" not in _categories(doc)
    assert r.returncode == 0


def test_coupling_and_ground_caps_are_told_apart_by_node_count(tmp_path):
    """IEEE-1481: `idx node value` is grounded, `idx node1 node2 value` is
    coupling. Nothing else distinguishes them."""
    import spef_extraction_check as S
    sf = tmp_path / "x.spef"
    sf.write_text(_HEADER + "*D_NET *39 1.0\n*CAP\n"
                  "1 *39:A 1e-5\n"
                  "2 *39:A *40:B 2e-5\n"
                  "*RES\n1 *39:A *39:8 41.8\n"
                  "*END\n")
    facts = S.scan_spef(sf)
    assert facts["ground_caps"] == 1
    assert facts["coupling_caps"] == 1
    # *RES entries are 4 tokens too — they must not be counted as coupling.
    assert facts["d_nets"] == 1


@pytest.mark.parametrize("text,nets", [
    (_spef(nets=8, coupling=False), 8),
    (_spef(nets=8, coupling=True), 8),
])
def test_this_counter_agrees_with_the_plugins_canonical_cap_reader(text, nets,
                                                                   tmp_path):
    """Two parsers for one file format drift apart; pin them together.

    `phase3_one_shot_runner._parse_spef_caps` is the canonical IEEE-1481 *CAP
    reader (it is what `_emit_spef_coupling_augment` and the SI chain use).
    This checker reimplements the classification rather than importing a
    30k-line module, so the agreement has to be asserted, not assumed.
    """
    import spef_extraction_check as S
    import phase3_one_shot_runner as R
    sf = tmp_path / "x.spef"
    sf.write_text(text)
    facts = S.scan_spef(sf)
    cg, cc = R._parse_spef_caps(text)
    assert (facts["coupling_caps"] > 0) == bool(cc), (facts, sorted(cc))
    assert (facts["ground_caps"] > 0) == bool(cg), (facts, sorted(cg))
    assert facts["d_nets"] == nets


# ===========================================================================
# DIRECTION-1 GUARDS — hold on the pre-fix tree too
# ===========================================================================
def test_d1_missing_extracted_dir_still_fails(tmp_path):
    r = subprocess.run([sys.executable, str(_PROG), str(tmp_path)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 1


def test_d1_empty_spef_still_fails(tmp_path):
    ext = tmp_path / "phase3" / "stage3" / "extracted"
    ext.mkdir(parents=True)
    (ext / "top.spef").write_text("")
    r, doc = _run(tmp_path)
    assert r.returncode == 1
    assert "EMPTY_SPEF" in _categories(doc)


def test_d1_sub_1kb_spef_still_fails(tmp_path):
    ext = tmp_path / "phase3" / "stage3" / "extracted"
    ext.mkdir(parents=True)
    (ext / "top.spef").write_text("*SPEF \"x\"\n*D_NET a 1\n")
    r, doc = _run(tmp_path)
    assert r.returncode == 1
    assert "TOO_SMALL" in _categories(doc)


def test_d1_missing_spef_header_still_fails(tmp_path):
    proj = _project(tmp_path, _name_map(1200) + _d_net(39, False))
    r, doc = _run(proj)
    assert r.returncode == 1
    assert "BAD_HEADER" in _categories(doc)


def test_d1_a_documented_waiver_still_short_circuits(tmp_path):
    (tmp_path / "waivers.json").write_text(json.dumps({
        "spef_extraction_unavailable_reason":
            "commercial PDK has no Magic .tech file for extraction"}))
    r, doc = _run(tmp_path)
    assert r.returncode == 0
    assert doc["summary"]["waived"] is True


def test_d1_a_healthy_spef_still_passes(tmp_path):
    proj = _project(tmp_path, _spef(nets=460))
    r, _ = _run(proj)
    assert r.returncode == 0
