"""Regression for GitHub issue #471 (HIGH) — spare_cell_preservation_check
was O(N_spares * artefact_size).

ISSUE 現象: per spare the check re.escape+searched the FULL text of each
artefact, and keep_attr_present_for compiled 7 regexes PER NAME and
re-scanned the full text, all driven by a per-spare loop. At a few
hundred spares x tens-of-MB artefacts (DEF + netlist) that is thousands
of full-text scans — it blew flow_compliance_check's 300s program budget
(child observed killed at ~287s CPU) and false-FAILed ('program timed
out') every CPU/SoC-class design whose spares genuinely survived. Only
small primitives escaped.

FIX: linearize. ONE pass per artefact builds an instance-name token set +
a keep/dont_touch-protected token set; per-spare verdicts become O(1) set
membership. Identical verdict semantics: genuinely-lost spares still FAIL,
preserved spares PASS.

This file builds a DEFECT-ARTIFACT fixture shaped like the issue (several
hundred spares x a multi-MB DEF), then EXECUTES the real program end-to-end
(CLI invocation, NOT just unit asserts) and asserts the END state:
  (a) wall-clock FAR below the 300s budget,
  (b) a preserved fixture PASSes,
  (c) a genuinely-missing-spare fixture still FAILs.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).parent.parent
sys.path.insert(0, str(PROGRAMS))

import spare_cell_preservation_check as pres  # noqa: E402

PRES_SCRIPT = PROGRAMS / "spare_cell_preservation_check.py"
assert PRES_SCRIPT.exists()

# Issue #471 budget: flow_compliance_check kills child programs at 300s.
# A linearized check must finish with enormous head-room; we assert a hard
# ceiling and report the real number.
BUDGET_S = 300.0
PERF_CEILING_S = 30.0   # the issue's explicit "FAR below" bar
N_SPARES = 400          # "several hundred spares"
N_NORMAL = 6000         # non-spare cells, to inflate the artefact
MIN_DEF_MB = 2.0        # "a multi-MB DEF"


# ──────────────────────────────────────────────────────────────────
# Defect-artifact fixture builders (synthetic, structural shapes).
# ──────────────────────────────────────────────────────────────────
def _spare_names(n):
    return [f"spare_inst_{i}" for i in range(n)]


def _big_def(spare_names, *, normal=N_NORMAL, tagged=True, drop=()):
    """A multi-MB DEF: N_NORMAL ordinary placed cells + every spare as a
    COMPONENT. `tagged` -> spares get '+ FIXED' (keep-protected); `drop`
    -> a set of spare names that an optimizer stripped (absent entirely).
    A trailing comment block pads the file past MIN_DEF_MB."""
    drop = set(drop)
    lines = ["VERSION 5.8 ;", "DESIGN top ;",
             f"COMPONENTS {normal + len(spare_names)} ;"]
    for i in range(normal):
        lines.append(
            f"  - _ord_{i}_ STD_CELL_PRIMITIVE + PLACED "
            f"( {i * 13 % 900000} {i * 7 % 900000} ) N ;")
    status = "+ FIXED" if tagged else "+ PLACED"
    for nm in spare_names:
        if nm in drop:
            continue
        lines.append(
            f"  - {nm} STD_CELL_PRIMITIVE {status} ( 100 100 ) N ;")
    lines.append("END COMPONENTS")
    body = "\n".join(lines)
    # Pad past the multi-MB bar with inert comment lines.
    pad_unit = "// inert filler line padding the artefact " + "x" * 40
    pad = "\n".join(pad_unit for _ in range(60000))
    return body + "\n" + pad


def _write_project(tmp_path, plan):
    pnr = tmp_path / "phase3/stage3/pnr"
    pnr.mkdir(parents=True)
    (pnr / "spare_cells.json").write_text(json.dumps(plan))
    return tmp_path


def _plan(spare_names):
    return {
        "count": len(spare_names),
        "instances": [{"name": nm, "type": "inverter",
                       "cell": "STD_CELL_PRIMITIVE"} for nm in spare_names],
        "spare_pads": [],
    }


# ──────────────────────────────────────────────────────────────────
# (1) PERF — the issue's core symptom. Multi-MB DEF x hundreds of spares
#     must complete FAR below the 300s budget. End-to-end CLI invocation.
# ──────────────────────────────────────────────────────────────────
def test_issue471_perf_multi_mb_def_completes_far_below_budget(tmp_path,
                                                               capsys):
    names = _spare_names(N_SPARES)
    plan = _plan(names)
    proj = _write_project(tmp_path, plan)
    def_text = _big_def(names, tagged=True)
    def_mb = len(def_text.encode("utf-8")) / 1e6
    assert def_mb >= MIN_DEF_MB, f"fixture not multi-MB: {def_mb:.2f} MB"
    (proj / "phase3/stage3/pnr/routed.def").write_text(def_text)

    # Real, end-to-end program invocation (NOT a unit call) — exactly the
    # shape flow_compliance_check spawns.
    t0 = time.monotonic()
    cp = subprocess.run(
        [sys.executable, str(PRES_SCRIPT), str(proj),
         "--json", str(tmp_path / "perf.json")],
        capture_output=True, text=True)
    wall = time.monotonic() - t0

    rep = json.loads((tmp_path / "perf.json").read_text())

    # END STATE — capture the verbatim numbers for the acceptance record.
    end_state = (
        f"[issue#471 perf] spares={N_SPARES} def={def_mb:.2f}MB "
        f"wall={wall:.3f}s budget={BUDGET_S:.0f}s "
        f"verdict={rep['verdict']} survived={rep['survived']} "
        f"inserted={rep['inserted']} rc={cp.returncode}")
    with capsys.disabled():
        print("\n" + end_state)

    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert rep["verdict"] == "PASS", rep
    assert rep["survived"] == N_SPARES and rep["inserted"] == N_SPARES
    # The whole point of #471: not just "under 300s" but FAR below it.
    assert wall < PERF_CEILING_S, (
        f"took {wall:.3f}s — must be far below the {BUDGET_S:.0f}s budget")
    assert wall < BUDGET_S


# ──────────────────────────────────────────────────────────────────
# (2) REGRESSION — preserved spares (multi-MB) PASS end-to-end.
# ──────────────────────────────────────────────────────────────────
def test_issue471_preserved_fixture_passes_cli(tmp_path):
    names = _spare_names(250)
    proj = _write_project(tmp_path, _plan(names))
    (proj / "phase3/stage3/pnr/routed.def").write_text(
        _big_def(names, tagged=True))
    cp = subprocess.run(
        [sys.executable, str(PRES_SCRIPT), str(proj)],
        capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert '"verdict": "PASS"' in cp.stdout


# ──────────────────────────────────────────────────────────────────
# (3) REGRESSION — a genuinely-missing spare still FAILs (verdict
#     semantics unchanged by the linearization).
# ──────────────────────────────────────────────────────────────────
def test_issue471_genuinely_missing_spare_still_fails_cli(tmp_path):
    names = _spare_names(250)
    proj = _write_project(tmp_path, _plan(names))
    stripped = names[123]   # optimizer removed exactly one spare
    (proj / "phase3/stage3/pnr/routed.def").write_text(
        _big_def(names, tagged=True, drop={stripped}))
    cp = subprocess.run(
        [sys.executable, str(PRES_SCRIPT), str(proj)],
        capture_output=True, text=True)
    assert cp.returncode == 1, cp.stdout + cp.stderr
    rep = json.loads(
        (proj / "reports/spare_preservation.json").read_text())
    assert rep["verdict"] == "FAIL"
    assert any(x["name"] == stripped for x in rep["removed"])


# ──────────────────────────────────────────────────────────────────
# (4) REGRESSION — present-but-untagged (lost keep attr) still FAILs
#     when the artefact set is keep-capable.
# ──────────────────────────────────────────────────────────────────
def test_issue471_present_but_untagged_still_fails(tmp_path):
    names = _spare_names(200)
    # tagged=False -> '+ PLACED' (not FIXED); add an unrelated dont_touch
    # so the artefact set IS keep-capable.
    def_text = _big_def(names, tagged=False) + "\nset_dont_touch some_other"
    r = pres.evaluate_preservation(_plan(names), {"def": def_text})
    assert r["verdict"] == "FAIL"
    assert r["keep_check_applied"] is True
    assert len(r["untagged"]) == len(names)
    assert r["removed"] == []


# ──────────────────────────────────────────────────────────────────
# (5) VERDICT-IDENTITY — the linearized path must produce the SAME
#     verdict as the original per-name regex semantics across a battery
#     of edge cases (direction-aware keep forms, GDS-only, multi-artefact,
#     empty artefacts, token-boundary look-alikes).
# ──────────────────────────────────────────────────────────────────
def _reference_present(name, text):
    import re
    if not name or not text:
        return False
    return re.search(r"(?<![A-Za-z0-9_])" + re.escape(name)
                     + r"(?![A-Za-z0-9_])", text) is not None


def _reference_keep(name, texts):
    import re
    nre = re.escape(name)
    pats = [
        re.compile(r"set_dont_touch\b[^\n]*\b" + nre + r"\b"),
        re.compile(r"\bdont_touch\b[^\n]*\b" + nre + r"\b"),
        re.compile(nre + r"\b[^\n]*\bdont_touch\b"),
        re.compile(r"\(\*[^\n]*\bkeep\b[^\n]*\*\)[^\n]*\b" + nre + r"\b"),
        re.compile(nre + r"\b[^\n]*\bkeep\b"),
        re.compile(r"\b" + nre + r"\b[^\n]*\+\s*FIXED\b"),
        re.compile(r"\b" + nre + r"\b[^\n]*\+\s*COVER\b"),
    ]
    for t in texts.values():
        if not t:
            continue
        for p in pats:
            if p.search(t):
                return True
    return False


def _reference_eval(plan, texts):
    spares = pres._spare_names_and_types(plan)
    removed, untagged, survived = [], [], set()
    any_keep = any(("dont_touch" in t or "keep" in t or "FIXED" in t
                    or "COVER" in t) for t in texts.values() if t)
    for name, typ in spares:
        if not any(_reference_present(name, t) for t in texts.values()):
            removed.append(name)
            continue
        survived.add(name)
        if any_keep and not _reference_keep(name, texts):
            untagged.append(name)
    return {"removed": sorted(removed), "untagged": sorted(untagged),
            "survived": len(survived), "any_keep": any_keep}


@pytest.mark.parametrize("names,texts", [
    (["a", "b", "c"], {"def": "  - a x + FIXED ;\n  - b x + FIXED ;"
                              "\n  - c x + FIXED ;"}),
    (["a", "b", "c"], {"def": "  - a x + PLACED ;\nset_dont_touch b\nc keep"}),
    (["a", "b", "c"], {"gds": "SNAME a\nSNAME b\nSNAME c"}),
    (["a", "b"], {"def": "  - a x + PLACED ;\n  - b x + PLACED ;"
                         "\nset_dont_touch other"}),
    (["a", "b"], {"def": "(* keep *) wire a ;\nb dont_touch"}),
    (["a", "b", "gone"], {"def": "a + FIXED\nb + COVER"}),
    (["x_1", "x_10"], {"net": "set_dont_touch x_1\nx_10 keep"}),
    (["n"], {"def": "dont_touch n", "net": "n + FIXED"}),
    (["a"], {"def": "", "gds": "SNAME a"}),
    # token-boundary look-alike: 'spare_1' must NOT match inside 'spare_10'
    (["spare_1"], {"def": "  - spare_10 x + FIXED ;"}),
])
def test_issue471_verdict_identical_to_reference(names, texts):
    plan = _plan(names)
    new = pres.evaluate_preservation(plan, texts)
    ref = _reference_eval(plan, texts)
    assert sorted(x["name"] for x in new["removed"]) == ref["removed"]
    assert sorted(x["name"] for x in new["untagged"]) == ref["untagged"]
    assert new["survived"] == ref["survived"]
    assert new["keep_check_applied"] == ref["any_keep"]


# ──────────────────────────────────────────────────────────────────
# (6) The retained backward-compat helpers stay verdict-identical.
# ──────────────────────────────────────────────────────────────────
def test_issue471_helpers_still_consistent():
    texts = {"def": "  - a x + FIXED ;\nset_dont_touch b\nc keep"}
    assert pres.name_present_in_text("a", texts["def"]) is True
    assert pres.name_present_in_text("zz", texts["def"]) is False
    assert pres.keep_attr_present_for("a", texts) is True   # + FIXED
    assert pres.keep_attr_present_for("b", texts) is True   # set_dont_touch
    assert pres.keep_attr_present_for("c", texts) is True   # keep
    assert pres.keep_attr_present_for("missing", texts) is False
