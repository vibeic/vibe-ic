#!/usr/bin/env python3
"""spef_extraction_check could not see the axis its consumers are denominated in.

THE BLINDNESS. `scan_spef` built `{has_header, has_design, d_nets, r_nets}` —
four facts about RECORDS and none about what those records CONTAIN. A SPEF whose
`*CAP` bodies are all grounded (3 tokens) and the byte-for-byte same design with
2-node coupling entries (4 tokens) produced an IDENTICAL report: same `d_nets`,
same `has_nets`, same rc, same findings. Every downstream SI / crosstalk gate is
denominated in coupling caps, and the artefact-level check they all sit on could
not say whether a single one existed.

WHAT THIS ADDS, AND WHAT IT DELIBERATELY DOES NOT. It adds counts
(`grounded_caps`, `coupling_caps`, `has_coupling`) and one INFO finding naming a
grounded-only extraction. It does NOT add a failure: a grounded-only extraction
is a legitimate mode, and this gate's question is "was extraction produced", not
"was it coupled". `test_d1_rc_is_unchanged_in_both_directions` is the two-sided
control — the same rc on a coupled and a grounded-only SPEF, and it holds on the
pre-change tree too, which is the point.

The gate that must not sign off on a zero here is the SI gate that consumes it;
that is `si_mcf_sta_check`, pinned by
`test_si_zero_coupling_is_not_a_signoff.py`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "spef_extraction_check.py"

_HEADER = (
    '*SPEF "ieee 1481-1999"\n'
    '*DESIGN "top"\n'
    '*DATE "2026-07-27"\n'
    "*DIVIDER /\n*DELIMITER :\n*BUS_DELIMITER []\n"
    "*T_UNIT 1 NS\n*C_UNIT 1 PF\n*R_UNIT 1 OHM\n*L_UNIT 1 HENRY\n\n"
)


def _name_map(n: int) -> str:
    return "*NAME_MAP\n" + "".join(
        f"*{39 + i} _an_internal_net_name_{i:05d}_\n" for i in range(n)) + "\n"


def _d_net(idx: int, coupling: bool) -> str:
    """One *D_NET record. A *CAP entry is `id node value` (grounded, 3 tokens)
    or `id nodeA nodeB value` (coupling, 4 tokens) — the field count is the
    only difference, and it is the only thing these fixtures vary."""
    cap = (f"1 *{idx}:D 2.96094e-05\n"
           f"2 *{idx}:Y 0.000193369\n"
           f"3 *{idx}:8 0.000222979\n")
    if coupling:
        cap += f"4 *{idx}:8 *{idx + 1}:8 1.23e-05\n"
    return (f"*D_NET *{idx} 0.000445958\n"
            f"*CONN\n"
            f"*I *{idx}:D I *D some_dff\n"
            f"*I *{idx}:Y O *D some_nor2\n"
            f"*CAP\n{cap}"
            f"*RES\n1 *{idx}:Y *{idx}:8 41.8334\n"
            f"*END\n\n")


def _spef(nets: int = 40, coupling: bool = False) -> str:
    return (_HEADER + _name_map(40)
            + "".join(_d_net(39 + i, coupling) for i in range(nets)))


def _project(tmp: Path, text: str) -> Path:
    ext = tmp / "phase3" / "stage3" / "extracted"
    ext.mkdir(parents=True, exist_ok=True)
    (ext / "design.spef").write_text(text)
    return tmp


def _run(proj: Path):
    out = proj / "out.json"
    r = _pr.run([sys.executable, str(_PROG), str(proj),
                        "--json", str(out)],
                       capture_output=True, text=True)
    return r, json.loads(out.read_text())


def _categories(doc):
    return [f["category"] for f in doc["findings"]]


def test_the_two_fixtures_differ_only_in_coupling_lines():
    coupled, grounded = _spef(coupling=True), _spef(coupling=False)
    dropped = [ln for ln in coupled.splitlines() if ln.startswith("4 *")]
    assert len(dropped) == 40, dropped[:3]
    assert [ln for ln in coupled.splitlines()
            if not ln.startswith("4 *")] == grounded.splitlines()


# ===========================================================================
# THE DEFECT: the two were indistinguishable in this gate's output
# ===========================================================================
def test_a_grounded_only_spef_is_disclosed_as_such(tmp_path):
    _, doc = _run(_project(tmp_path, _spef(coupling=False)))
    s = doc["summary"]
    assert s["coupling_caps"] == 0, s
    assert s["has_coupling"] is False, s
    assert s["grounded_caps"] == 120, s          # 40 nets x 3 grounded entries
    assert "NO_COUPLING_CAPS" in _categories(doc), doc["findings"]


def test_a_coupled_spef_is_disclosed_as_such(tmp_path):
    _, doc = _run(_project(tmp_path, _spef(coupling=True)))
    s = doc["summary"]
    assert s["coupling_caps"] == 40, s
    assert s["has_coupling"] is True, s
    assert "NO_COUPLING_CAPS" not in _categories(doc)


def test_the_two_reports_are_no_longer_substantively_identical(tmp_path):
    """The defect stated as one assertion: same design, coupling axis flipped,
    and every SUBSTANCE field of the two summaries compared equal.

    `total_bytes` is excluded deliberately, and excluding it is the point. It
    did differ on origin/main — a coupled SPEF has more lines than a grounded
    one — but a byte count is not a statement about coupling: it moves with net
    count, name-map length and formatting alike, so a reader can conclude
    nothing about coupling from it. Every field that MEANT something was
    identical."""
    _, g = _run(_project(tmp_path / "g", _spef(coupling=False)))
    _, c = _run(_project(tmp_path / "c", _spef(coupling=True)))
    gs = {k: v for k, v in g["summary"].items() if k != "total_bytes"}
    cs = {k: v for k, v in c["summary"].items() if k != "total_bytes"}
    assert gs != cs, (
        "a grounded-only and a coupled extraction still report identically on "
        "every field that means anything")


def test_a_commented_coupling_line_is_not_a_coupling_cap(tmp_path):
    """A mention is not a record — the same rule the record counters already
    hold to."""
    text = _spef(nets=1, coupling=False).replace(
        "*RES\n", "// 4 *39:8 *40:8 1.23e-05\n*RES\n", 1)
    _, doc = _run(_project(tmp_path, text))
    assert doc["summary"]["coupling_caps"] == 0, doc["summary"]


def test_res_entries_are_not_counted_as_caps(tmp_path):
    """*RES bodies are `id nodeA nodeB value` — the SAME 4-token shape as a
    coupling cap. Counting them would fabricate coupling on every SPEF."""
    _, doc = _run(_project(tmp_path, _spef(nets=40, coupling=False)))
    assert doc["summary"]["coupling_caps"] == 0, (
        "*RES entries leaked into the coupling count")


# ===========================================================================
# NO FALSE ALARM — controls, green on origin/main too
# ===========================================================================
def test_d1_rc_is_unchanged_in_both_directions(tmp_path):
    """CONTROL, green on the pre-change tree as well, and deliberately so:
    disclosure must not move any rc."""
    rg, g = _run(_project(tmp_path / "g", _spef(coupling=False)))
    rc, c = _run(_project(tmp_path / "c", _spef(coupling=True)))
    assert rg.returncode == 0 and rc.returncode == 0
    assert g["summary"]["pass"] is True and c["summary"]["pass"] is True


def test_d1_a_headerless_spef_still_fails(tmp_path):
    r, doc = _run(_project(tmp_path, _name_map(40) + _d_net(39, False) * 40))
    assert r.returncode == 1
    assert "BAD_HEADER" in _categories(doc)


def test_d1_a_netless_spef_still_warns_and_claims_no_coupling(tmp_path):
    """A file with no nets gets NO_NETS and must NOT also get the grounded-only
    disclosure — "no coupling here" is a claim about an extraction that exists."""
    r, doc = _run(_project(tmp_path, _HEADER + _name_map(400)))
    assert doc["summary"]["has_nets"] is False
    assert "NO_NETS" in _categories(doc)
    assert "NO_COUPLING_CAPS" not in _categories(doc)
    assert r.returncode == 0
