#!/usr/bin/env python3
"""A campaign document may not ask for a fix the tree already carries.

WHAT HAPPENED. `ppa-e2e/RESULT.md` and its generator carried, in a present-tense
**REQUESTS TO THE LANDER** list ranked by value, request #1: *"Three
`puts "STA_BASIS: POST_ROUTE_SPEF"` lines, in the emitters that write
`sta_spef_multicorner.rpt` and `sta_mcorner_ocv.rpt`. Today they stamp nothing"*.
Those three `puts` had landed in `e4c5840d6` (v1.11.57, 2026-08-21) together
with their own guard, and request #2 in the same list — the Phase-3 power
session — landed in that same commit. The list went on asking for both.

THE HARM IS NOT HYPOTHETICAL. An agent reading that list in order to explain 144
`SCOPE_INCOMPLETE` refusals filed the residual as a live FOURTH producer defect
and reported it as such. It was not a producer defect at all: the emitters stamp,
and the run trees that still refuse are simply OLDER than the fix. Measured
2026-08-22 on one host -- every `sta_mcorner_ocv.rpt` / `sta_spef_multicorner.rpt`
written before 2026-08-21 carries no stamp and every one written after carries
it, and the six run trees split on exactly that line: stamped -> 0 refusals,
unstamped -> 48 each. A document that misdescribes the tree tells a reader to
stop looking where the answer is -- `PPA_INTERFACES` §2.1 says exactly this about
a scope gap, and it is just as true of a request list.

THE RULE. A satisfied request is MARKED, never deleted -- the finding was true
when it was written and the record of it is worth keeping. What may not survive
is the present tense.

NON-VACUITY IS THE LOAD-BEARING PART, twice over. A test that only greps for an
absent phrase passes on an empty file, on a renamed file, and on a file it never
opened. So this file first proves it is reading the real artefacts: the runner
must emit each of the four materially different stamp/stage pairs from synthetic
fixtures, and each document must still carry the same conditional truth. A
source grep for `STA_BASIS:` cannot establish either fact: the token may sit in
an unreachable arm, or every arm may stamp the flattering extracted stage. Only
then is the absence of the stale claim allowed to mean anything.
"""
from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]
RUNNER = (Path(__file__).resolve().parent.parent / "phase3_one_shot_runner.py")
GENERATOR = REPO / "docs" / "campaigns" / "ppa-e2e" / "tools" / "gen_result_md.py"
RESULT_MD = REPO / "docs" / "campaigns" / "ppa-e2e" / "RESULT.md"
FINDINGS_MD = REPO / "docs" / "campaigns" / "ppa-e2e" / "FINDINGS.md"

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
_SPEC = importlib.util.spec_from_file_location(
    "phase3_one_shot_runner_record_truth", RUNNER)
p3 = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = p3
_SPEC.loader.exec_module(p3)

from _ppa import timing  # noqa: E402
from _ppa.backends import opensta  # noqa: E402

#: These are required shipped artefacts.  There is deliberately no skip for a
#: checkout that lacks one: the tests below must fail when their subject is
#: absent, renamed, or unreadable rather than turning missing evidence into a
#: non-blocking result.

#: The sign-off STA emitters the satisfied request named. Every one of them must
#: write a basis stamp; this list is the reason the request is satisfied.
_EMITTERS = ("_emit_spef_sta", "_emit_corner_spef_sta", "_emit_mcorner_ocv_sta")

#: Present-tense claims that the emitters do not stamp. Matched case-insensitively
#: and across a line break, because the documents are hard-wrapped and the claim
#: straddled one. PAST tense is deliberately NOT here -- "at the time they
#: stamped nothing" is the record of a finding and must stay readable.
_STALE = (
    r"today\s+they\s+stamp\s+nothing",
    r"they\s+stamp\s+nothing\s*,",
    r"emitters\s+stamp\s+nothing",
)

#: Text that proves this test opened the document it means to check. If a
#: document is renamed, restructured or emptied, these vanish and the test fails
#: rather than passing over an artefact it never read.
_ANCHOR = {
    "gen_result_md.py": "REQUESTS TO THE LANDER",
    "RESULT.md": "REQUESTS TO THE LANDER",
    "FINDINGS.md": "F-6 — the multi-corner sign-off STA reports",
}

_COMMIT = "e4c5840d6"

#: The exact conditional statement the three current prose sites must carry.
#: It names four arms even though two share one stamp/stage pair; collapsing
#: them to "all extracted" is the regression this continuation repairs.
_CONDITIONAL_TRUTH = (
    "`PRE_LAYOUT_ESTIMATE` -> `pre_layout_estimate` for RC pre-layout and for "
    "OCV pre-layout; `POST_ROUTE_NO_SPEF` -> `post_route_no_extraction` for "
    "routed OCV without SPEF; and `POST_ROUTE_SPEF` -> "
    "`post_route_extracted` for routed OCV with SPEF"
)

#: The EXACT marking, not the bare word. `SATISFIED` already appears in these
#: documents for unrelated reasons -- as a feasibility-axis verdict in four
#: RESULT.md table rows and two FINDINGS.md lines -- so asserting the bare word
#: would have passed on a document carrying none of this lane's markings at all.
#: That is not hypothetical: it passed exactly that way once, on a checkout
#: where the markings had been reverted.
_MARKING = f"**SATISFIED by `{_COMMIT}` (v1.11.57, 2026-08-21)"

#: The four sections this lane marked, and where each one ENDS. Checked PER
#: SECTION rather than per document, because a per-document check is satisfied
#: by any ONE surviving marking: dropping the commit id from F-6 while F-7 kept
#: its own left the whole file passing. MEASURED -- that mutation came out
#: green, which is why the rule below is scoped to the section.
_SECTIONS = {
    "gen_result_md.py": (
        ("**1 — `phase3_one_shot_runner.py`: stamp the multi-corner STA emitters**",
         "**2 — `phase3_one_shot_runner.py`"),
        ("**2 — `phase3_one_shot_runner.py`: fix the Phase-3 power session**",
         "**3 —"),
    ),
    "RESULT.md": (
        ("**1 — `phase3_one_shot_runner.py`: stamp the multi-corner STA emitters**",
         "**2 — `phase3_one_shot_runner.py`"),
        ("**2 — `phase3_one_shot_runner.py`: fix the Phase-3 power session**",
         "**3 —"),
    ),
    "FINDINGS.md": (
        ("## F-6 — the multi-corner sign-off STA reports", "## F-7 —"),
        ("## F-7 — the Phase-3 power report", "## F-8"),
    ),
}

#: A commit id as these documents spell one.
_COMMITISH = re.compile(r"\b[0-9a-f]{7,40}\b")

TOP = "dut"
CONTAINER = "test-container-no-such-container"
_PUTS = re.compile(r'puts \$_f "([^"]*)"')

#: emitter, routed netlist present, SPEF present, exact emitted stamp, exact
#: stage resolved by `_ppa/timing`. The ids are deliberately arm names: a
#: mutation failure must tell the reader which semantic condition was lost.
_SEMANTIC_ARMS = (
    ("rc_pre_layout", "rc", False, True,
     "PRE_LAYOUT_ESTIMATE", "pre_layout_estimate"),
    ("ocv_pre_layout", "ocv", False, True,
     "PRE_LAYOUT_ESTIMATE", "pre_layout_estimate"),
    ("ocv_routed_without_spef", "ocv", True, False,
     "POST_ROUTE_NO_SPEF", "post_route_no_extraction"),
    ("ocv_routed_with_spef", "ocv", True, True,
     "POST_ROUTE_SPEF", "post_route_extracted"),
)


def _emitter_sources() -> dict:
    """Each named emitter's own source segment, by AST rather than by line math.

    A regex over the whole 41k-line runner would find a stamp written by some
    OTHER function and call this one stamped, which is the vacuous pass this
    test exists to refuse.
    """
    text = RUNNER.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(text)
    out = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in _EMITTERS:
            out[node.name] = ast.get_source_segment(text, node) or ""
    return out


def _mk_project(root: Path, *, routed: bool) -> Path:
    """The smallest tree that makes both shipped emitters answer."""
    synth = root / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (synth / f"{TOP}_synth.v").write_text(f"module {TOP}(); endmodule\n")
    pnr = root / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "constraint.sdc").write_text(
        "create_clock -period 10 [get_ports clk]\n")
    if routed:
        (pnr / f"{TOP}_pnr.v").write_text(f"module {TOP}(); endmodule\n")
    libdir = root / "input" / "pdk" / "liberty"
    libdir.mkdir(parents=True)
    for name in ("cellib_ss.lib", "cellib_typ.lib", "cellib_ff.lib"):
        (libdir / name).write_text("library (l) { }\n")
    return root


def _mk_pdk(root: Path) -> "p3.PdkConfig":
    libdir = root / "input" / "pdk" / "liberty"
    return p3.PdkConfig(
        name="testpdk", liberty=str(libdir / "cellib_typ.lib"),
        tech_lef=str(root / "tech.lef"), cell_lef=str(root / "cell.lef"),
        cell_gds=None, site="unit", drc_deck=None)


def _mk_spefs(root: Path) -> dict:
    spef_dir = root / "phase3" / "stage3" / "extracted" / "spef_corners"
    spef_dir.mkdir(parents=True)
    out = {}
    for corner in ("min", "max"):
        path = spef_dir / f"{TOP}.{corner}.spef"
        path.write_text('*SPEF "IEEE 1481-1998"\n')
        out[corner] = path
    return out


@pytest.fixture(autouse=True)
def _no_docker(monkeypatch):
    """Emit the real Tcl while replacing only the unavailable tool process."""
    monkeypatch.setitem(p3._CONTAINER_MOUNTS_CACHE, CONTAINER, [])

    def _fake_exec(container, cmd, *args, **kwargs):
        for output in kwargs.get("outputs") or []:
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_text("worst slack max 1.00\ntns max 0.00\n")
        return 0, "", ""

    monkeypatch.setattr(p3, "_docker_exec", _fake_exec)


def _report_body(tcl: str) -> str:
    """The report lines generated by this emitter Tcl, in emission order."""
    return "\n".join(_PUTS.findall(tcl))


def _emit_rc(root: Path, *, routed: bool) -> str:
    project = _mk_project(root, routed=routed)
    report = project / "phase3" / "stage3" / "sta" / "sta_spef_multicorner.rpt"
    result = p3._emit_corner_spef_sta(
        project, TOP, _mk_pdk(project), CONTAINER, _mk_spefs(project),
        report, [], corner_libs=None)
    assert result["ok"] is True
    return _report_body((report.parent / "sta_spef_setup.tcl").read_text())


def _emit_ocv(root: Path, *, routed: bool, with_spef: bool) -> str:
    project = _mk_project(root, routed=routed)
    libdir = project / "input" / "pdk" / "liberty"
    corner_libs = {
        "SS": str(libdir / "cellib_ss.lib"),
        "FF": str(libdir / "cellib_ff.lib"),
    }
    report = project / "phase3" / "stage3" / "sta" / "sta_mcorner_ocv.rpt"
    ran = p3._emit_mcorner_ocv_sta(
        project, TOP, _mk_pdk(project), CONTAINER, corner_libs,
        _mk_spefs(project) if with_spef else {}, None, report, [])
    assert ran is True
    return _report_body(
        (report.parent / "sta_mcorner_ocv_setup.tcl").read_text())


def _section(body: str, start: str, stop: str) -> str:
    """One uniquely anchored section, refusing absence or ambiguity."""
    assert body.count(start) == 1, (
        f"expected one section start {start!r}, found {body.count(start)}")
    begin = body.index(start)
    assert stop in body[begin + len(start):], (
        f"section beginning {start!r} has no closing anchor {stop!r}")
    end = body.index(stop, begin + len(start))
    return body[begin:end]


# ------------------------------------------------------- NON-VACUITY FIRST ---
def test_the_three_named_emitters_still_exist_in_the_runner():
    """If they were renamed, every assertion below would be about nothing."""
    found = _emitter_sources()
    missing = [n for n in _EMITTERS if n not in found]
    assert not missing, (
        f"emitter(s) {missing} are no longer module-level functions of "
        f"{RUNNER.name}; this guard's subject moved and the guard must move "
        f"with it rather than quietly passing")


@pytest.mark.parametrize(
    "arm,emitter,routed,with_spef,expected_stamp,expected_stage",
    _SEMANTIC_ARMS, ids=[case[0] for case in _SEMANTIC_ARMS])
def test_each_emitted_stamp_resolves_to_its_exact_timing_stage(
        tmp_path: Path, arm: str, emitter: str, routed: bool,
        with_spef: bool, expected_stamp: str, expected_stage: str):
    """The four-arm positive control; source-token grepping cannot replace it."""
    root = tmp_path / arm
    body = (_emit_rc(root, routed=routed) if emitter == "rc" else
            _emit_ocv(root, routed=routed, with_spef=with_spef))
    parsed = opensta.parse_report(body)
    stage, gap = timing._stage_for(parsed)
    assert parsed.basis_stamp == expected_stamp, (
        f"{arm}: emitted {parsed.basis_stamp!r}, expected {expected_stamp!r}; "
        f"report body:\n{body}")
    assert (stage, gap) == (expected_stage, None), (
        f"{arm}: `_ppa/timing` resolved stamp {parsed.basis_stamp!r} as "
        f"stage={stage!r}, gap={gap!r}; expected stage={expected_stage!r}")


@pytest.mark.parametrize("doc", [GENERATOR, RESULT_MD, FINDINGS_MD],
                         ids=lambda p: p.name)
def test_the_document_this_test_checks_is_the_one_it_opened(doc: Path):
    """Second non-vacuity control, per document."""
    body = doc.read_text(encoding="utf-8", errors="replace")
    anchor = _ANCHOR[doc.name]
    assert anchor in body, (
        f"{doc.name} no longer contains {anchor!r}; the stale-claim check "
        f"below would pass over a document it does not understand")


# ------------------------------------------------------------- THE RULE ------
@pytest.mark.parametrize("doc", [GENERATOR, RESULT_MD, FINDINGS_MD],
                         ids=lambda p: p.name)
def test_no_campaign_document_claims_the_emitters_stamp_nothing(doc: Path):
    """The rule, and it only means anything because of the two tests above."""
    body = doc.read_text(encoding="utf-8", errors="replace")
    for pattern in _STALE:
        hit = re.search(pattern, body, re.IGNORECASE)
        assert hit is None, (
            f"{doc.name} states, in the present tense, that the sign-off STA "
            f"emitters do not stamp: {hit.group(0)!r}. They do -- "
            f"{', '.join(_EMITTERS)} each write a `STA_BASIS:` line, since "
            f"{_COMMIT}. Mark the request SATISFIED and keep it; do not delete "
            f"it, and do not leave it in the present tense")


@pytest.mark.parametrize("doc", [GENERATOR, RESULT_MD, FINDINGS_MD],
                         ids=lambda p: p.name)
def test_each_current_prose_site_states_the_four_arm_conditional_truth(doc: Path):
    """The narrative must agree with the emitted/result mapping above."""
    body = doc.read_text(encoding="utf-8", errors="replace")
    start, stop = _SECTIONS[doc.name][0]
    lines = []
    for line in _section(body, start, stop).splitlines():
        line = line.strip()
        if line.startswith(">"):
            line = line[1:].lstrip()
        lines.append(line)
    section = " ".join(" ".join(lines).split())
    assert _CONDITIONAL_TRUTH in section, (
        f"{doc.name}: the satisfied STA section does not state the four-arm "
        f"conditional mapping. Expected this exact truth:\n"
        f"{_CONDITIONAL_TRUTH}\nSection was:\n{section}")


@pytest.mark.parametrize("doc", [GENERATOR, RESULT_MD, FINDINGS_MD],
                         ids=lambda p: p.name)
def test_the_satisfied_marking_names_the_commit_that_satisfied_it(doc: Path):
    """A bare "SATISFIED" is an unexplained overwrite of a finding.

    The same discipline `_ppa/contract` applies to a metric authority: a
    resolution with no stated reason is not a resolution.
    """
    body = doc.read_text(encoding="utf-8", errors="replace")
    assert _MARKING in body, (
        f"{doc.name} carries no SATISFIED marking naming {_COMMIT}. Either the "
        f"marking was dropped, or a request was marked satisfied without "
        f"naming what satisfied it -- an unexplained overwrite of a finding")
    marked = 0
    for start, stop in _SECTIONS[doc.name]:
        assert start in body, (
            f"{doc.name}: section {start[:48]!r} is gone; this check would "
            f"pass over a request it can no longer find")
        seg = body[body.index(start):]
        seg = seg[:seg.index(stop, len(start))] if stop in seg[len(start):] else seg
        if "SATISFIED" not in seg:
            continue
        marked += 1
        assert _COMMITISH.search(seg), (
            f"{doc.name}: the section beginning {start[:48]!r} is marked "
            f"SATISFIED and names no commit. A resolution with no stated "
            f"reason is an unexplained overwrite of a finding -- the same rule "
            f"`_ppa/contract` applies to a metric authority")
    assert marked, (
        f"{doc.name}: neither marked section says SATISFIED any more, so the "
        f"per-section rule above asserted nothing")


def test_the_generator_and_its_committed_output_do_not_drift():
    """`RESULT.md` is `gen_result_md.py`'s output and NOTHING re-derives it.

    The generator hard-codes a run tree that no longer exists, so it cannot be
    run to check. Compare the entire static request section, not two stamp
    tokens that can agree while the surrounding claims drift.
    """
    gen = GENERATOR.read_text(encoding="utf-8", errors="replace")
    out = RESULT_MD.read_text(encoding="utf-8", errors="replace")
    start, stop = "## REQUESTS TO THE LANDER", "## Where everything is"
    gen_section = _section(gen, start, stop)
    out_section = _section(out, start, stop)
    assert gen_section == out_section, (
        "gen_result_md.py and RESULT.md disagree in their generated request "
        "section; the generator cannot be re-run to settle the drift")
