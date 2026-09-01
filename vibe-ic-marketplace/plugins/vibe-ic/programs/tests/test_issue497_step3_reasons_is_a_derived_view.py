"""#497 step 3 — `reasons` is RENDERED FROM the records, not authored beside
them.

WHAT CHANGED
------------
Until step 3 the P0 umbrella stated every gate's outcome TWICE: once as the
prose payload of whichever bucket the outcome belonged to, and once as a
record. Two statements in two vocabularies, editable apart. The worker now
returns only the RECORD; the three buckets are projected from the records by
`_p0_buckets_from_records`, and `reasons` is composed from that projection by
`_compose_p0_reasons_from_records`. There is exactly one authoring site per
gate, so prose and payload cannot disagree — not because a test compares them,
but because there is only one of them.

WHAT MUST NOT CHANGE
--------------------
The operator-facing per-step listing renders `reasons`. #492 exists precisely
because gates that never ran used to be invisible there, so a naive move of the
disclosure into a field of its own would have undone it. Every one of the six
line shapes is therefore pinned here as GOLDEN TEXT, stated in full: Form 1,
Form 2 (header + bullets), the disclosure (heading + bullets), plain SKIP,
WAIVED-DEFERRED, the clean-sweep line, and the umbrella's own no-RTL note.

THE NO-GATE SKIP LINE, decided deliberately
-------------------------------------------
`SKIP: no RTL directory found — structural gates skipped (analog track /
pre-RTL)` names NO gate, yet it has always worn the per-gate `SKIP: ` prefix
and lived in the per-gate skip bucket — a non-gate line inside the per-gate
grammar, one shape away from the collision that let the #492 disclosure be read
as 37 failing gates. In the record-driven world it is an UMBRELLA-LEVEL NOTE:
emitted from the umbrella's own tri-state, never a record, never inside the
per-gate population. Its rendering is unchanged, prefix included, because the
operator's line is a contract this migration does not get to alter on the way
past.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN_ROOT / "programs"
sys.path.insert(0, str(PROGRAMS))
import _gate_invocation as GI  # noqa: E402
import flow_compliance_check as F  # noqa: E402
import _spawn_stub  # noqa: E402


def _project_with_rtl(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    (proj / "rtl").mkdir(parents=True)
    (proj / "rtl" / "top.v").write_text(
        "module top(input a, output b); assign b = a; endmodule\n")
    return proj


def _rec(name, verdict, message="", **evidence):
    return F._p0_gate_record(name, verdict, message, evidence)


_DERIVE = object()   # `executed=None` is a REAL value: "nothing dispatched"


def _reasons(records, executed=_DERIVE, n_registered=241):
    if executed is _DERIVE:
        executed = not any(r["verdict"] == "FAIL" for r in records)
    return F._compose_p0_reasons_from_records(records, executed, n_registered)


# ═════════════════ 1. the six shapes, as golden text ═══════════════════════
def test_form1_exactly_one_failure():
    assert _reasons([_rec("alpha_check", "FAIL", "boom", exit_code=1)]) == [
        "FAIL: alpha_check — boom"]


def test_form2_two_or_more_failures():
    assert _reasons([_rec("alpha_check", "FAIL", "boom", exit_code=1),
                     _rec("bravo_check", "FAIL", "bang", exit_code=1)]) == [
        "Failed gates (2):",
        "  - alpha_check — boom",
        "  - bravo_check — bang"]


def test_the_form_is_chosen_by_the_failure_count_and_nothing_else():
    """The variable that emptied `failed_gates` for years was the COUNT."""
    one = _reasons([_rec("alpha_check", "FAIL", "boom", exit_code=1)])
    two = _reasons([_rec("alpha_check", "FAIL", "boom", exit_code=1),
                    _rec("bravo_check", "FAIL", "boom", exit_code=1)])
    assert not any(r.startswith("Failed gates") for r in one)
    assert two[0] == "Failed gates (2):"


def test_the_timeout_fail_has_no_message_separator():
    """The one FAIL whose line is a sentence the umbrella wrote itself."""
    assert _reasons([_rec("alpha_check", "FAIL", "timed out",
                          timeout_s=60)]) == ["FAIL: alpha_check timed out"]


def test_plain_skip_shapes():
    assert _reasons([
        _rec("alpha_check", "SKIP", "", exit_code=2,
             skip_kind="input-missing"),
        _rec("bravo_check", "SKIP", "class N/A",
             skip_kind="class-not-applicable")]) == [
        "SKIP: alpha_check",
        "SKIP: bravo_check (SKIP: class N/A)"]


def test_waived_deferred_shape():
    w = {"gate": "alpha_check", "review_required": True, "ticket": "T-9",
         "evidence": "why-detail", "reason": "thin-input",
         "first_line": "the gate said this"}
    assert _reasons([F._p0_waiver_record(w)]) == [
        "WAIVED-DEFERRED: alpha_check — thin-input (ticket=T-9, "
        "review_required=true): the gate said this"]


def test_the_disclosure_block_heading_and_bullets():
    ni = [_rec(f"unreached_{i}_check", "NOT_INVOCABLE",
               "argparse rejected the umbrella's argv: bad option",
               exit_code=2) for i in range(2)]
    got = _reasons(ni, n_registered=241)
    assert got == [
        GI.format_not_invocable_heading(2, 241),
        f"  - {GI.format_not_invocable_entry(ni[0]['name'], ni[0]['message'])}",
        f"  - {GI.format_not_invocable_entry(ni[1]['name'], ni[1]['message'])}",
    ]
    assert GI.is_not_invocable_heading(got[0])
    assert all(GI.is_not_invocable_disclosure(x) for x in got[1:])


def test_clean_sweep_line():
    assert _reasons([_rec("alpha_check", "PASS", exit_code=0)]) == [
        "every registered structural-RTL gate that dispatched "
        "PASSED (0 FAIL / 0 SKIP / 0 WAIVED)"]


def test_the_umbrella_note_is_not_a_gate_record():
    """The no-RTL line: rendered from the tri-state, absent from the records."""
    assert _reasons([], executed=None) == [f"SKIP: {F._P0_NO_RTL_NOTE}"]
    # ...and the same records with a dispatched umbrella say the opposite
    assert _reasons([], executed=True) == [
        "every registered structural-RTL gate that dispatched "
        "PASSED (0 FAIL / 0 SKIP / 0 WAIVED)"]
    assert not any(g in F._P0_NO_RTL_NOTE for g in F._STRUCTURAL_RTL_GATES)


def test_the_umbrella_note_never_enters_the_per_gate_skip_population(
        monkeypatch):
    """The deliberate decision, pinned where it is actually visible.

    Putting the note back into the skip bucket renders IDENTICALLY — same
    prefix, same position — so no assertion on the output can tell the two
    apart. What it destroys is the property the decision is for: that the
    per-gate population never contains a line naming no gate, which is the
    shape that let a disclosure bullet be read as a failing gate.

    So this asserts on the ARGUMENTS crossing the renderer's boundary, which is
    a real interface, not the source text: the per-gate skips must be empty and
    the note must arrive on the channel that exists for statements about the
    umbrella itself.
    """
    seen = {}
    real = F._compose_p0_reasons

    def _spy(s_fails, s_skips, s_waivers, n_registered=None,
             umbrella_notes=None):
        seen.update(fails=list(s_fails), skips=list(s_skips),
                    waivers=list(s_waivers),
                    notes=list(umbrella_notes or []))
        return real(s_fails, s_skips, s_waivers, n_registered,
                    umbrella_notes=umbrella_notes)

    monkeypatch.setattr(F, "_compose_p0_reasons", _spy)
    out = F._compose_p0_reasons_from_records([], None, 241)

    assert out == [f"SKIP: {F._P0_NO_RTL_NOTE}"]
    assert seen["notes"] == [F._P0_NO_RTL_NOTE]
    assert seen["skips"] == [], (
        "the umbrella's note about itself must not be filed as a per-gate skip")
    assert seen["fails"] == [] and seen["waivers"] == []


def test_all_shapes_at_once_keep_their_order():
    """Failures, then the disclosure, then skips, then waivers."""
    w = {"gate": "wv_check", "review_required": True, "ticket": "T-1",
         "evidence": "d", "reason": "thin-input", "first_line": "why"}
    got = _reasons([
        _rec("a_check", "FAIL", "boom", exit_code=1),
        _rec("b_check", "FAIL", "bang", exit_code=1),
        _rec("ni_check", "NOT_INVOCABLE", "argparse said no", exit_code=2),
        _rec("sk_check", "SKIP", "", exit_code=2, skip_kind="input-missing"),
        F._p0_waiver_record(w),
        _rec("ok_check", "PASS", exit_code=0),
    ], n_registered=6)
    assert got == [
        "Failed gates (2):",
        "  - a_check — boom",
        "  - b_check — bang",
        GI.format_not_invocable_heading(1, 6),
        f"  - {GI.format_not_invocable_entry('ni_check', 'argparse said no')}",
        "SKIP: sk_check",
        "WAIVED-DEFERRED: wv_check — thin-input (ticket=T-1, "
        "review_required=true): why",
    ]
    assert not any("ok_check" in line for line in got), (
        "a passing gate contributes no line — the fact that made "
        "passed_gate_count unrecoverable from this list")


# ═════════ 2. the waiver mirror pair, which is the one drift risk ══════════
@pytest.mark.parametrize("w", [
    {"gate": "g_check", "review_required": True, "ticket": "T-1",
     "evidence": "detail text", "reason": "thin-input",
     "first_line": "the first line"},
    {"gate": "h_check", "review_required": False, "ticket": None,
     "evidence": "", "reason": "", "first_line": ""},
])
def test_waiver_record_and_entry_are_exact_inverses(w):
    """`_p0_waiver_record` and `_p0_waiver_entry` are hand-written mirrors.

    KEY ORDER included: the waiver dict is published verbatim as
    `thin_input_waivers` in the `--json` report.
    """
    back = F._p0_waiver_entry(F._p0_waiver_record(w))
    assert back == w
    assert list(back) == list(w)


def test_the_real_waiver_shapes_round_trip(tmp_path, monkeypatch):
    """The two waiver shapes the umbrella actually builds, through the real
    dispatch — not a hand-typed dict."""
    monkeypatch.setenv("VIBE_IC_COMPLIANCE_WORKERS", "1")
    proj = _project_with_rtl(tmp_path)
    monkeypatch.setattr(F, "_STRUCTURAL_RTL_GATES",
                        tuple(F._THIN_INPUT_WAIVER_GATES))
    # Anchored at the SPAWN (`subprocess.Popen`), so this keeps working
    # whichever helper the umbrella launches through — see `_spawn_stub`.
    _spawn_stub.stub_spawn(monkeypatch, lambda _s: (1, "gate first line\n"))
    records: list = []
    _passed, _fails, _skips, waivers = F._run_structural_rtl_gates(
        proj, allow_thin_input=True, records_out=records)
    assert waivers, "fixture must reach the waiver branch"
    waived = [r for r in records if r["verdict"] == "WAIVED"]
    assert [F._p0_waiver_entry(r) for r in waived] == waivers
    assert [list(F._p0_waiver_entry(r)) for r in waived] == \
        [list(w) for w in waivers]


# ══════ 3. end to end: prose the records do not support cannot exist ═══════
def _run_main(tmp_path, monkeypatch, records, fabricated_fails, extra=()):
    proj = _project_with_rtl(tmp_path)

    def _stub(_project, **kw):
        out = kw.get("records_out")
        if out is not None:
            out.extend(records)
        # The prose buckets carry a fabrication the records do not support.
        return (not any(r["verdict"] == "FAIL" for r in records),
                list(fabricated_fails), ["zzz_fabricated_skip"], [])

    monkeypatch.setattr(F, "_run_structural_rtl_gates", _stub)
    report = tmp_path / "report.json"
    rc = F.main([str(proj), "--json", str(report), *extra])
    return rc, json.loads(report.read_text())


def test_reasons_cannot_be_written_by_anything_but_the_records(
        tmp_path, monkeypatch, capsys):
    """The direct proof that `reasons` is derived.

    Before step 3 the umbrella's prose buckets WERE the reasons list, so this
    fixture's fabrication would appear verbatim in the operator listing and in
    the published report. It now cannot: the buckets are not read.
    """
    _rc, report = _run_main(
        tmp_path, monkeypatch,
        records=[_rec("real_check", "FAIL", "the real line", exit_code=1)],
        fabricated_fails=["FAIL: zzz_fabricated_check — invented"])
    printed = capsys.readouterr().out
    p0 = next(s for s in report["steps"] if s["id"] == "P0")
    assert p0["reasons"] == ["FAIL: real_check — the real line"]
    assert "zzz_fabricated_check" not in printed
    assert "zzz_fabricated_skip" not in printed


def test_every_reason_line_is_traceable_to_a_record_or_the_umbrella_note(
        tmp_path):
    """A real full-registry run: nothing in the list comes from nowhere."""
    proj = _project_with_rtl(tmp_path)
    report = tmp_path / "report.json"
    F.main([str(proj), "--json", str(report), "--lenient"])
    p0 = next(s for s in json.loads(report.read_text())["steps"]
              if s["id"] == "P0")
    records = p0["gate_records"]
    assert records, "fixture must dispatch the registry"
    expected = F._compose_p0_reasons_from_records(
        records, not any(r["verdict"] == "FAIL" for r in records),
        len(F._STRUCTURAL_RTL_GATES))
    assert p0["reasons"] == expected
    # every line either names a recorded gate or is one of the two headings
    named = {r["name"] for r in records}
    for line in p0["reasons"]:
        if (line.startswith("Failed gates")
                or GI.is_not_invocable_heading(line.strip())):
            continue
        assert any(g in line for g in named), (
            f"reason line traces to no record: {line[:80]!r}")


def test_the_operator_still_sees_every_reason_line(tmp_path, capsys):
    """#492/#1968: every non-PASS disposition stays visible to the operator."""
    proj = _project_with_rtl(tmp_path)
    report = tmp_path / "report.json"
    F.main([str(proj), "--json", str(report), "--lenient"])
    printed = capsys.readouterr().out
    p0 = next(s for s in json.loads(report.read_text())["steps"]
              if s["id"] == "P0")
    for line in p0["reasons"]:
        assert f"└─ {line}" in printed, (
            f"reason line vanished from the operator listing: {line[:70]!r}")
    assert not any(GI.is_not_invocable_heading(x.strip())
                   for x in p0["reasons"])
    assert GI.NOT_INVOCABLE_HEADING_SENTINEL not in printed
    assert any("N/A from the design declaration roster" in x
               for x in p0["reasons"]), (
        "the fixture must visibly exercise the declaration-derived N/A arm")
