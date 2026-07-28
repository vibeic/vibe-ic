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

DENOMINATOR — and it is total. Over every tracked `.spef` in the repo
(`git ls-files benchmark-data` -> 20 files) the first `*D_NET` record lies
beyond byte 8192 in 20 of 20; offsets span 12,834 - 109,782 bytes in files
carrying 351 - 2,563 nets. `NO_NETS` was false for every SPEF this plugin has
ever published, so removing those findings deletes a finding with no true
instance, not a real check.

THE PREDICATE THAT ALSO MOVED, which the first version of this change did not
say. `BAD_HEADER` (ERROR, rc 1) and `MISSING_METADATA` (WARNING) were decided
on the same 8 KB prefix. A VALID SPEF whose `*SPEF` header sits past byte 8192
was `ERROR BAD_HEADER` rc 1 before and is clean rc 0 now — an rc 1 -> 0 move,
i.e. a relaxation, and the intended one. `test_a_late_header_is_no_longer_a_
false_bad_header` executes exactly that file, and
`test_d1_missing_spef_header_still_fails` is the two-sided control proving the
ERROR did not become unreachable. No tracked SPEF has a late header; the case
is constructed here.

WHAT IT COSTS. Nothing in rc for any real artefact, and one full streaming read
of each SPEF instead of an 8 KB slice.

DIRECTION-1 GUARDS (`test_d1_*`) hold on the pre-fix tree too.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

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
                       capture_output=True, text=True, timeout=60)
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
# The rc-BEARING predicate the window also moved
# ===========================================================================
def test_a_late_header_is_no_longer_a_false_bad_header(tmp_path):
    """The disclosure, EXECUTED. A well-formed SPEF whose `*SPEF` header sits
    past byte 8192 (behind a long tool banner) was `ERROR BAD_HEADER` rc 1 on
    the pre-change tree purely because the header was outside the read window.

    This is the one rc 1 -> 0 move in the change, and it is stated in the
    module docstring and in `spef_extraction_check`'s. Constructed rather than
    taken from the corpus: no tracked SPEF has a late header.
    """
    banner = "".join(f"// OpenROAD extraction log line {i:05d}\n"
                     for i in range(400))
    assert len(banner) > 8192, len(banner)
    text = banner + _HEADER + _name_map(1200) + _d_net(39, False)
    assert text.index("*SPEF") > 8192, "fixture does not reproduce the case"
    r, doc = _run(_project(tmp_path, text))
    assert "BAD_HEADER" not in _categories(doc), (
        "a valid SPEF is still failed for a header the old window could not "
        "reach")
    assert r.returncode == 0


def test_late_metadata_is_no_longer_a_false_missing_metadata(tmp_path):
    """Same move, the WARNING half: `*DESIGN` / `*DATE` past 8 KB."""
    banner = "".join(f"// banner {i:05d}\n" for i in range(900))
    assert len(banner) > 8192
    text = ('*SPEF "ieee 1481-1999"\n' + banner
            + '*DESIGN "top"\n*DATE "x"\n' + _name_map(1200)
            + _d_net(39, False))
    _, doc = _run(_project(tmp_path, text))
    assert "MISSING_METADATA" not in _categories(doc), doc["findings"]


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
