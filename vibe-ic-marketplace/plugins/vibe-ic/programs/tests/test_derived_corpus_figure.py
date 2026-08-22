#!/usr/bin/env python3
"""A stated justification must be checkable.

The motivating measurement, reproduced in `test_the_motivating_funnel_shape_is_caught`:
a guard narrowed its predicate from a stated 113 raw matches to 13 to 5. The 13
and the 5 reproduce exactly. The 113 reproduces under no reading of the clause
it describes — reconstructions of the same predicate measured 41, 49, 71, 440
and 595 on this tree. The narrowing is sound; one of the figures offered in
support of it is not evidence, because a reader cannot get it back out.

These tests are written against OBSERVABLE PROPERTIES — what a docstring says
about this checkout, and what the guard reports for a given corpus — never
against the identity of a helper. A different correct fix (a different seam
name, a different placeholder syntax, a hand-rolled renderer) passes all of
them.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
sys.path.insert(0, str(PROGRAMS))

import _derived_corpus_figure as seam            # noqa: E402
import derived_corpus_figure_check as guard      # noqa: E402

#: Bound for the one launch in this file. NOT a round number picked by feel:
#: `ci_harness_timeout_ceiling_check` (BLOCKING) resolves the pytest harness
#: bound from `tools/gatekeeper-land.sh` — `--timeout=180`,
#: `--timeout-method=thread` — and permits any ONE blocking call at most
#: `180 // 3` = 60 s. Above that the inner bound can never fire: pytest reaches
#: 180 s first and takes the whole SESSION down, so `--maxfail` stops counting
#: and every other file in the subset loses its verdict, including files that
#: had already passed.
#: The landed value was 900 — five times the harness, so it could never fire.
#: MEASURED here: the sweep walks the >3000 `.py` under `programs/` that the
#: test below asserts a denominator for, and takes 9.02 s. This is the slowest
#: bounded call in this batch that still fits, so the headroom is stated rather
#: than assumed: 60 s is 6.6x measured, and the figure grows with the tree.
_SWEEP_TIMEOUT_S = 60


# --------------------------------------------------------------------------
# helpers — deliberately independent of the module under test
# --------------------------------------------------------------------------
def _module_doc(path: Path) -> str:
    return ast.get_docstring(ast.parse(path.read_text(errors="replace"))) or ""


def _rendered_doc(path: Path) -> str:
    """The module docstring with live figures, falling back to the raw text.

    The fallback is what makes these behavioural controls rather than
    missing-symbol ones: a checkout with no bindings still produces a string,
    so the assertion below fails on a VALUE, not on an import error.
    """
    doc = _module_doc(path)
    figures = guard.declared_figures(path)
    if figures is None:
        return doc
    return seam.render(doc, figures.evaluate_all(PLUGIN))


def _write_corpus(root: Path, **modules: str) -> Path:
    for name, text in modules.items():
        (root / f"{name}.py").write_text(text)
    return root


#: A module that walks a tree — otherwise the funnel clause is out of scope.
_WALKER = 'from pathlib import Path\n\n\ndef sweep(r):\n    return list(Path(r).rglob("*.py"))\n'


@pytest.fixture(scope="module")
def corpus_findings():
    """One real sweep of programs/, shared — it costs ~25s."""
    return guard.sweep(PLUGIN, PROGRAMS)


# ==========================================================================
# 1. THE CONTROLS — these fail on the pre-fix tree, on a value difference
# ==========================================================================
def _flow_declared_gate_programs_independently() -> set:
    """Programs the flow declares as gate clauses, re-derived HERE.

    Deliberately NOT `checker_execution_wiring_audit.flow_declared_gate_programs`.
    The point of this module is that a stated figure is checkable by a reader
    who does not trust the module under test, and calling that module's own
    helper would make the check a tautology — it would agree with the docstring
    for the same reason the docstring is written, which is no evidence at all.

    Read from the YAML STRUCTURE, never its text (vibe-ic#1012: a substring test
    counted a program named in a COMMENT as wired). Both slots that dispatch a
    program are read, and only programs this checkout actually SHIPS are
    counted, matching the rule `checker_population` states in prose:
    a clause naming a program that is not here is a different defect and
    `gate_is_wired` owns it.
    """
    flow = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
    if not flow.is_file():
        return set()
    import yaml  # noqa: PLC0415

    names: set = set()

    def walk(node):
        if isinstance(node, dict):
            for key, val in node.items():
                if key in ("program_exit_zero", "advisory_program_exit_zero"):
                    if isinstance(val, str) and val.split():
                        names.add(val.split()[0] + ".py")
                elif key == "optional_program_exit_zero":
                    cmd = val.get("command") if isinstance(val, dict) else None
                    if isinstance(cmd, str) and cmd.split():
                        names.add(cmd.split()[0] + ".py")
                else:
                    walk(val)
        elif isinstance(node, list):
            for val in node:
                walk(val)

    walk(yaml.safe_load(flow.read_text(errors="replace")))
    return {n for n in names if (PROGRAMS / n).is_file()}


def test_wiring_audit_docstring_states_this_checkouts_populations():
    """The populations the docstring argues from must be THIS tree's.

    Computed here independently of the module under test. Before the original
    fix the docstring said 533 / 560 / 1091 and this tree said something else,
    so it failed on a VALUE with the same code running on both sides.

    THE CHECKER-SHAPED POPULATION IS NOT A FILENAME GLOB, AND THIS TEST USED TO
    SAY IT WAS (measured on `ab5a23a28`: it demanded 595 while the docstring
    correctly rendered 603, an eight-program gap).

    `checker_population` is the filename glob UNION the programs the flow
    declares as gate clauses, and its own docstring gives the reason: *"A gate
    is in this population because the flow runs it, not because somebody named
    it `*_check.py`."* That union is vibe-ic#1130 — "THE FILENAME GLOB IS STILL
    A NAME LIST, and #693 only made it a longer one". The eight this tree adds
    are real gates the flow runs under names no suffix matches:

        bsdl_emit.py                    metal_fill_emit.py
        coverage_closure.py             mixed_signal_top_lvs_run.py
        fmeda_fault_injection_coverage.py   phase1_expert_parse_track.py
        route_congestion_trade_disclosure.py verilator_coverage_measure.py

    So the glob-only figure describes neither the population the audit uses nor
    anything it claims, and demanding the docstring state it would force the
    module to publish a number that contradicts its own denominator. The
    independent computation is re-derived from the flow YAML here rather than
    imported, so this stays a check a distrustful reader can run.
    """
    target = PROGRAMS / "checker_execution_wiring_audit.py"
    as_shipped = len({p.name for suf in ("*_check.py", "*_audit.py")
                      for p in PROGRAMS.glob(suf)})
    by_name = {p.name for suf in ("*_check.py", "*_audit.py", "*_guard.py",
                                  "*_lint.py", "*_gate.py")
               for p in PROGRAMS.glob(suf)}
    checker_shaped = len(by_name | _flow_declared_gate_programs_independently())
    all_programs = len(list(PROGRAMS.glob("*.py")))

    # The union must be a real widening on this tree, or the control above is
    # measuring the glob under a longer name and would pass unchanged if the
    # #1130 rule were reverted.
    assert checker_shaped > len(by_name), (
        "the flow declares no gate program outside the filename glob, so this "
        "test cannot tell the #1130 union apart from the glob it replaced")

    rendered = _rendered_doc(target)
    for label, value in (("as-shipped", as_shipped),
                         ("checker-shaped", checker_shaped),
                         ("all programs", all_programs),
                         ("outside", all_programs - checker_shaped)):
        assert re.search(rf"(?<!\d){value}(?!\d)", rendered), (
            f"docstring does not state this checkout's {label} population "
            f"({value}); it is arguing from a figure nothing recomputed")


def test_l_doc_scope_figures_are_pinned_or_derived():
    """Its scope argument rests on an L-corpus count, and the corpus grows.

    Pre-fix the paragraph reads "which is exactly the 2554-document L corpus"
    with nothing saying when that was true; the same glob returns a different
    number now. Post-fix every paragraph that states a population figure also
    carries a pin.
    """
    doc = _module_doc(PROGRAMS / "l_doc_path_portability_check.py")
    unpinned = [para for _off, para in guard.paragraphs(doc)
                if guard.population_figures(para)
                and not guard._PIN.search(para)
                and not seam.PLACEHOLDER_RE.search(para)]
    assert unpinned == [], (
        "population figure stated with neither a pin nor a derivation:\n"
        + "\n---\n".join(unpinned))


def test_the_guard_reports_no_blocking_finding_on_this_tree(corpus_findings):
    blocking = [f for f in corpus_findings if f["blocking"]]
    assert blocking == [], "\n".join(
        f"{f['file']}:{f['line']} {f['rule']}: {f['detail']}" for f in blocking)


# ==========================================================================
# 2. THE SWEEP MUST DEMONSTRABLY FIRE — the rule applied to my own evidence
# ==========================================================================
def test_the_motivating_funnel_shape_is_caught(tmp_path):
    """The exact sentence shape this rule was written for.

    Pure grammar with invented names — no PDK, vendor or design literal.
    """
    _write_corpus(tmp_path, narrowing_guard=(
        '"""Find per-source record merges decided by discovery order.\n'
        "\n"
        "THE PREDICATE\n"
        "-------------\n"
        "  3. ACC is a MAPPING, decided from its binding in the enclosing\n"
        "     function. This clause alone takes 113 syntactic matches down to\n"
        "     13 candidates; the 8 it cannot classify are skipped.\n"
        '"""\n' + _WALKER))
    findings = guard.sweep(tmp_path, tmp_path)
    funnels = [f for f in findings if f["rule"] == "funnel-literal"]
    assert len(funnels) == 1, findings
    assert funnels[0]["blocking"] is True
    assert "113" in " ".join(funnels[0]["literals"])


def test_the_sweep_is_not_vacuous_on_the_real_corpus(corpus_findings):
    """A sweep that reports nothing at all is indistinguishable from a broken one.

    The blocking tier is empty by construction once the tree is fixed, so the
    thing that proves this predicate still touches real code is the ADVISORY
    tier. If this ever reaches zero, the predicate stopped reaching the corpus
    — that is a finding about the guard, not a clean bill of health.
    """
    advisory = [f for f in corpus_findings if not f["blocking"]]
    assert advisory, (
        "the sweep found nothing at all on a corpus measured to contain "
        "unpinned population figures; suspect the predicate, not the tree")
    assert len({f["file"] for f in advisory}) >= 3


def test_the_sweep_reaches_the_whole_programs_tree():
    """Disclose the denominator (vibe-ic#447): a narrowed sweep must not read as full."""
    swept = sum(1 for _ in PROGRAMS.rglob("*.py"))
    assert swept > 3000, swept
    out = subprocess.run(
        [sys.executable, str(PROGRAMS / "derived_corpus_figure_check.py"),
         "--no-evaluate"],
        capture_output=True, text=True, timeout=_SWEEP_TIMEOUT_S)
    assert str(swept) in out.stdout, out.stdout[:400]


# ==========================================================================
# 3. THE REVERSE CASES — every one is an over-correction that must NOT happen
# ==========================================================================
def test_a_pinned_historical_measurement_is_left_alone(tmp_path):
    """The "derive everything" over-correction.

    A figure recording what was measured when a decision was taken must NOT be
    re-derived. Re-deriving it silently replaces the input to the decision with
    today's number and destroys the only thing that makes the decision
    reviewable. This is the direction that erases evidence, so it is a reverse
    case and not a gap.
    """
    _write_corpus(tmp_path, pinned=(
        '"""A gate with a dated record.\n'
        "\n"
        "Measured 2026-08-03 in 581a8759, before choosing: the population was\n"
        "533 files, which narrowed to 31 candidates.\n"
        '"""\n' + _WALKER))
    assert guard.sweep(tmp_path, tmp_path) == []


def test_a_threshold_constant_is_not_a_population_figure(tmp_path):
    """The "any integer near a noun" over-correction.

    ">= 2 entries" is a rule parameter. Flagging it would push authors to delete
    the numbers that define the rule, which is strictly worse than prose drift.
    """
    _write_corpus(tmp_path, thresholds=(
        '"""A schema gate.\n'
        "\n"
        "Each field MUST carry at least 2 entries and fewer than 16 entries,\n"
        "narrowing to at most 4 candidates.\n"
        '"""\n' + _WALKER))
    assert guard.sweep(tmp_path, tmp_path) == []


def test_a_module_that_walks_no_tree_is_out_of_scope(tmp_path):
    """The "flag every docstring" over-correction.

    A module that cannot walk the corpus cannot derive a figure about it, so
    demanding derivation there demands the impossible.
    """
    _write_corpus(tmp_path, pure=(
        '"""A pure function.\n'
        "\n"
        "Reduces 113 candidate encodings down to 13 legal ones.\n"
        '"""\n\n\ndef f(x):\n    return x\n'))
    assert guard.sweep(tmp_path, tmp_path) == []


def test_advisory_findings_never_change_the_exit_code(tmp_path):
    """The "block on everything detectable" over-correction.

    The advisory tier reports a population the program is NOT entitled to
    triage — it cannot tell a claim about the corpus now from a record of a
    measurement then. Blocking on it would make the guard demand that authors
    delete honest history.
    """
    _write_corpus(tmp_path, advisory_only=(
        '"""A gate.\n'
        "\n"
        "The corpus holds 464 tracked files and 1628 occurrences of the shape.\n"
        '"""\n' + _WALKER))
    findings = guard.sweep(tmp_path, tmp_path)
    assert findings and all(not f["blocking"] for f in findings)
    rc = guard.main(["--programs", str(tmp_path), "--root", str(tmp_path)])
    assert rc == guard.RC_CLEAN


def test_render_refuses_an_unbound_placeholder_rather_than_emitting_blank():
    """The "render what you can" over-correction.

    Substituting an unknown placeholder with itself, or with nothing, puts the
    docstring back into the state the seam exists to prevent: prose that reads
    as a measurement and is not one. It must raise.
    """
    with pytest.raises(seam.FigureError):
        seam.render("population {figure:absent_one}", {"other": 3})
    assert seam.render("population {figure:present_one}", {"present_one": 7}) \
        == "population 7"


def test_bindings_are_not_cached_between_calls(tmp_path):
    """The "memoize for speed" over-correction — a cache reintroduces staleness."""
    calls = []

    def counting(root: Path) -> int:
        calls.append(root)
        return len(list(Path(root).glob("*.py")))

    figures = seam.CorpusFigures({"n": counting})
    (tmp_path / "a.py").write_text("")
    assert figures.evaluate("n", tmp_path) == 1
    (tmp_path / "b.py").write_text("")
    assert figures.evaluate("n", tmp_path) == 2, "a cached figure is a stale figure"
    assert len(calls) == 2


def test_a_lone_unpinned_figure_is_below_the_blocking_threshold(tmp_path):
    """Pins the SCOPE so nobody reads more into the gate than is there.

    A single stated figure with no pin is NOT blocked. The measured population
    of that shape on this tree is large and dominated by honest frozen records,
    so blocking it would be the "tighten until the count is zero" failure run
    backwards — noise until someone turns the gate off. Stated here as a test
    so the limit is a decision on the record, not an accident of the regex.
    """
    _write_corpus(tmp_path, lone=(
        '"""A gate.\n'
        "\n"
        "This check reads exactly the 2554-document corpus.\n"
        '"""\n' + _WALKER))
    assert [f for f in guard.sweep(tmp_path, tmp_path) if f["blocking"]] == []


# ==========================================================================
# 4. THE BINDING CONTRACT — no name allow-list; a site changes or stays flagged
# ==========================================================================
def test_a_placeholder_with_no_binding_blocks(tmp_path):
    _write_corpus(tmp_path, dangling=(
        '"""A gate reporting {figure:never_bound} files."""\n' + _WALKER))
    rules = {f["rule"] for f in guard.sweep(tmp_path, tmp_path)}
    assert "figure-unbound" in rules


def test_a_binding_no_docstring_names_blocks(tmp_path):
    _write_corpus(tmp_path, dead=(
        '"""A gate that mentions nothing."""\n'
        "import sys\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, {str(PROGRAMS)!r})\n"
        "from _derived_corpus_figure import CorpusFigures\n"
        "CORPUS_FIGURES = CorpusFigures({'unused_one': lambda r: 1})\n"
        + _WALKER))
    rules = {f["rule"] for f in guard.sweep(tmp_path, tmp_path)}
    assert "figure-unused" in rules


def test_a_binding_that_cannot_produce_an_int_blocks(tmp_path):
    _write_corpus(tmp_path, bad=(
        '"""A gate reporting {figure:not_an_int} files."""\n'
        "import sys\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, {str(PROGRAMS)!r})\n"
        "from _derived_corpus_figure import CorpusFigures\n"
        "CORPUS_FIGURES = CorpusFigures({'not_an_int': lambda r: 'many'})\n"
        + _WALKER))
    rules = {f["rule"] for f in guard.sweep(tmp_path, tmp_path)}
    assert "figure-uncomputable" in rules


def test_a_half_derived_paragraph_blocks(tmp_path):
    """Half a derived table is a table a reader will trust whole."""
    _write_corpus(tmp_path, half=(
        '"""A gate.\n'
        "\n"
        "The population is {figure:live_one} files, of which 31 candidates\n"
        "remain after clause 2.\n"
        '"""\n'
        "import sys\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, {str(PROGRAMS)!r})\n"
        "from _derived_corpus_figure import CorpusFigures\n"
        "CORPUS_FIGURES = CorpusFigures({'live_one': lambda r: 4})\n"
        + _WALKER))
    rules = {f["rule"] for f in guard.sweep(tmp_path, tmp_path)}
    assert "half-adopted" in rules


def test_the_fixed_form_is_accepted(tmp_path):
    """No name-based allow-list: a site stops being flagged by actually changing."""
    _write_corpus(tmp_path, fixed=(
        '"""A gate.\n'
        "\n"
        "The population is {figure:live_one} files on this checkout.\n"
        '"""\n'
        "import sys\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, {str(PROGRAMS)!r})\n"
        "from _derived_corpus_figure import CorpusFigures\n"
        "CORPUS_FIGURES = CorpusFigures({'live_one': lambda r: 4})\n"
        + _WALKER))
    assert guard.sweep(tmp_path, tmp_path) == []


def test_the_guard_is_wired_to_something_other_than_its_own_test():
    """`checker_execution_wiring_audit`'s rule, applied to this PR's own guard."""
    gates = (PLUGIN.parents[2] / "tools" / "ci" / "repo_hygiene_gates.sh")
    assert gates.is_file(), gates
    assert "derived_corpus_figure_check.py" in gates.read_text()


def test_this_gate_refuses_an_empty_population(tmp_path):
    """vibe-ic#564, applied to this PR's own gate.

    "No unrecomputed funnel found" over zero files is not a clean result, it is
    the absence of one — and the umbrella that aggregates this reads the exit
    code, not the prose. A gate shipped alongside a rule about honest evidence
    may not be the thing that returns a clean verdict having read nothing.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    assert guard.main(["--programs", str(empty),
                       "--root", str(tmp_path)]) == guard.RC_USAGE


def test_a_pass_discloses_its_denominator(tmp_path, capsys):
    """vibe-ic#447 — the verdict line itself must say how much was examined."""
    _write_corpus(tmp_path, clean='"""A gate with no figures."""\n' + _WALKER)
    assert guard.main(["--programs", str(tmp_path), "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "[PASS]" in out and "examined 1 file(s)" in out, out


def test_exit_codes_are_the_documented_three(tmp_path):
    _write_corpus(tmp_path, ok='"""A gate."""\n' + _WALKER)
    assert guard.main(["--programs", str(tmp_path), "--root", str(tmp_path)]) == 0
    assert guard.main(["--programs", str(tmp_path / "absent"),
                       "--root", str(tmp_path)]) == guard.RC_USAGE
    _write_corpus(tmp_path, boom=(
        '"""A gate narrowing 113 matches down to 13 candidates."""\n' + _WALKER))
    assert guard.main(["--programs", str(tmp_path),
                       "--root", str(tmp_path)]) == guard.RC_FOUND
