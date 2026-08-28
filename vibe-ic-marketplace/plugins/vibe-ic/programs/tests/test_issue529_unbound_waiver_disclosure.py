"""#529 — a `waivers`-dialect entry whose tier is not ENV_UNAVAILABLE was read
and then dropped without a word, and that is the whole corpus.

`_load_waivers` binds exactly one tier. Every other entry took a bare
`continue`, so a compliance report was BYTE-IDENTICAL whether the project
carried a ticketed, evidenced, `review_required: true` waiver or carried no
waivers.json at all. A reader could not tell "considered and inapplicable" from
"nobody read this file".

MEASURED over every tracked waivers.json, and pinned below:
    8 entries in the `waivers` dialect — verdict_tier WAIVED 7, PASS_STRUCTURAL 1
    0 entries with verdict_tier ENV_UNAVAILABLE

So all 8 hit that `continue`, and #216's "a rejected waiver must never vanish"
mechanism covered none of them.

WHAT THE OTHER TIERS ARE FOR — determined BY EXECUTION, not by reading. Each of
17 programs that read a project's waivers.json was run against three variants
of the same project, IN ITS OWN FRESH COPY (a first pass shared one directory
across all 17, and programs that write into the project — `waivers_materialize`
adds a `waived_steps` array, `final_report_generate` writes reports/ — then
changed what every later program saw; that confound produced one wrong reading,
so isolation is not optional here). The result, on both tiers the corpus
carries:

  * NO program anywhere branches on the tier VALUE except on the single string
    ENV_UNAVAILABLE — here, and `waiver_staleness.is_env_unavailable`.
    Replacing the tier with a garbage token changed no program's output, on the
    unfixed tree, for either `WAIVED` or `PASS_STRUCTURAL`.
    `PASS_STRUCTURAL` occurs exactly once in the whole repository, in one
    corpus file: no producer writes it and no reader tests it.
  * The ENTRY, however, is consumed — tier-blind — by five programs, each of
    which behaves differently with the entry present than with the file
    deleted: `waivers_schema_check` (validates it and warns),
    `waiver_legitimacy_check` (anti-pattern scan), `waiver_staleness_check`
    (aging), `phase1_no_waivers_used_check` (forbidden-name scan), and
    `final_report_generate`, which LISTS it in `reports/final_summary.md` under
    "Waivers (must be human-reviewed before tapeout)".

That is why the disclosure says the entry is READ AND EXAMINED but that its
tier binds nothing — and does not hand-wave that it is "for another consumer".
The tests below pin both halves, so neither claim can rot silently.

WHY A DISCLOSURE AND NOT A REJECTION. A `WAIVED`-tier entry is not an error; it
is not addressed to this checker at all. Filing it in `_ENV_WAIVER_REJECTIONS`
would say the step lost an exemption it never had, which is a second falsehood
in the opposite direction — the same distinction #524 drew when it kept its
uncorroborated-evidence advisories in a list separate from the rejections.
Every disclosure here is informational: no step verdict, no count and no exit
code moves.

AND NOTHING HERE MAY TAKE THE RUN DOWN (#519). `_load_waivers` wraps its body
in a handler that turns ANY exception into `SystemExit(1)`, so one mistyped
field used to delete the entire compliance report. That was not hypothetical:
against the unfixed tree a `verdict_tier` holding an int printed
`cannot parse …` and produced a ZERO-line report. Pinned below.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import _waiver_entries as _we  # noqa: E402
import waiver_staleness as _ws  # noqa: E402
from _published_corpus import corpus_root, needs_corpus  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

FCC = PROGRAMS / "flow_compliance_check.py"
WSC = PROGRAMS / "waivers_schema_check.py"

#: Repo root, from the plugin programs dir. The tracked corpus is READ here and
#: never written; every execution probe runs on a tmp_path project.
REPO_ROOT = PROGRAMS.parents[3]


def _corpus_dirs():
    """The two sub-trees of the PUBLISHED corpus that carry the `waivers`
    dialect, resolved at call time.

    This used to be a module-level tuple under `REPO_ROOT / "benchmark-data"`,
    and both halves of that stopped being right when the results moved to
    `vibeic/benchmark-data`:

    * the LOCATION moved, and only `corpus_root()` knows where it is now — it
      is what honours the `VIBE_IC_BENCHMARK_DATA` pointer;
    * the GUARD `CORPUS_DIRS[0].is_dir()` was a directory-existence test used to
      mean "the corpus is here", and it is no longer either. The path it named
      does not exist in this checkout at all, so the skip it was attached to
      never fired for the tests that FAILED; and `benchmark-data/` itself does
      still exist here — it holds the design INPUTS — so its presence would
      have proved nothing anyway. `@needs_corpus` asks whether a published CELL
      is readable, which is the question these three tests need answered.

    Resolved per call rather than at import so that the pointer is read when the
    test runs, not when the module is loaded.
    """
    root = corpus_root()
    assert root is not None, "@needs_corpus should have skipped before this point"
    return (root / "evaluation/phase1_parity", root / "ic")

SELF_REF = "reports/orchestrator/phase3_one_shot.json#steps[name=lvs]"

GOOD_RATIONALE = (
    "lvs step deferred: the netgen binary is not available in the current "
    "environment. ENV gap, NOT a design defect.")


def _entry(**over):
    """A well-formed `waivers`-dialect entry — ticket, evidence,
    review_required, substantive rationale — differing from an honoured one
    ONLY in its tier. That is the point: the entry is not defective."""
    e = {
        "step": "lvs",
        "phase": "3",
        "verdict_tier": "WAIVED",
        "rationale": GOOD_RATIONALE,
        "evidence": [SELF_REF],
        "ticket": "TAPEOUT-AUTOGEN-LVS",
        "review_required": True,
    }
    e.update(over)
    return e


def _project(tmp_path: Path, *entries, **extra_keys) -> Path:
    doc = {"_schema_version": "1", "waivers": list(entries)}
    doc.update(extra_keys)
    (tmp_path / "waivers.json").write_text(json.dumps(doc, indent=2))
    return tmp_path


def _load(project: Path):
    """Fresh call so the module-level disclosure list is read after the load it
    belongs to."""
    import flow_compliance_check as fcc
    waivers = fcc._load_waivers(project)
    return fcc, waivers


def _load_unvalidated(project: Path):
    """`_load_waivers` on its OWN ImportError fallback — the documented path
    that "loads without schema validation" when `waivers_schema_check` cannot
    be imported. Two of the loop's branches are only reachable there, because
    the validator rejects those shapes first; without exercising the fallback
    they would be untestable code, which is not code worth adding.

    `sys.modules[name] = None` is the supported way to make
    `from name import …` raise ImportError."""
    import flow_compliance_check as fcc
    sentinel = object()
    saved = sys.modules.get("waivers_schema_check", sentinel)
    sys.modules["waivers_schema_check"] = None
    try:
        return fcc, fcc._load_waivers(project)
    finally:
        if saved is sentinel:
            sys.modules.pop("waivers_schema_check", None)
        else:
            sys.modules["waivers_schema_check"] = saved


def _run_report(project: Path, out: Path):
    """Run the checker end-to-end and return (result, parsed report or None).

    The gate pool is forced SEQUENTIAL: with the default thread pool the text
    report is not reproducible even for one unchanged binary (five runs of the
    unfixed code on fresh copies of one corpus project printed
    `project_outputs_in_tree_check … in-tree self-reference(s)` counts
    2,4,4,4,4), which would make any A/B here measure the pool, not the code."""
    import os
    env = dict(os.environ, VIBE_IC_COMPLIANCE_WORKERS="1")
    r = _pr.run(
        [sys.executable, str(FCC), str(project), "--json", str(out)],
        capture_output=True, text=True, env=env)
    return r, (json.loads(out.read_text()) if out.is_file() else None)


def _disclosures(report) -> list:
    return [a for a in (report.get("advisories") or [])
            if a.startswith("WAIVER READ, NOT BOUND")
            or a.startswith("WAIVER ENTRY UNREADABLE")
            or a.startswith("WAIVER SUPERSEDED")]


# ----------------------------------------------------------------------
# 1. The corpus measurement the issue rests on, pinned
# ----------------------------------------------------------------------

def _tracked_waivers_json():
    """Every ``waivers.json`` THE CORPUS COMMIT CARRIES, from
    ``git ls-tree -r HEAD`` run inside the corpus checkout.

    NOT ``glob``. A local run leaves untracked `waivers.json` files under
    `benchmark-data/`, and this repo has host-local run directories that carry
    the `waivers` dialect — so a filesystem walk counts 10 entries here and 8 on
    a fresh checkout, making the pin below pass or fail depending on whose
    machine ran it. That is the failure #527 spent v1.7.86 removing from the d3
    dimension, in its own words: a file this commit does not carry is not
    evidence. The same rule applies to a corpus measurement.

    ``ls-tree -r HEAD`` rather than ``ls-files`` for the reason #527 documents:
    the index can carry a path this commit does not.

    THE REPOSITORY IT ASKS moved with the data. It asked THIS repo's HEAD, which
    is now the wrong tree to put the question to: the published cells are in
    `vibeic/benchmark-data`, so vibe-ic's HEAD answers "no waivers.json" — a
    true statement about vibe-ic and a false one about the corpus. Asking the
    corpus checkout keeps `tracked, not globbed` intact while making the
    `VIBE_IC_BENCHMARK_DATA` pointer mean something.
    """
    root = _corpus_root_dir()
    out = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "-z", "HEAD"],
        cwd=root, capture_output=True, text=True, check=True,
    ).stdout
    return sorted(
        root / rel
        for rel in out.split("\0")
        if rel.endswith("/waivers.json")
    )


def _corpus_root_dir():
    root = corpus_root()
    assert root is not None, "@needs_corpus should have skipped before this point"
    return root


def _corpus_waiver_entries():
    rows = []
    roots = [r.resolve() for r in _corpus_dirs()]
    for wf in _tracked_waivers_json():
        if not any(str(wf).startswith(str(r)) for r in roots):
            continue
        doc = json.loads(wf.read_text())
        for idx, entry in enumerate(
                _we.entries_by_key(doc).get("waivers", [])):
            rows.append((wf, idx, entry))
    return rows


@needs_corpus
def test_corpus_waivers_dialect_carries_no_env_unavailable_entry():
    """The measurement the whole issue turns on: every `waivers`-dialect entry
    in the corpus takes the tier `continue`, so #216's mechanism protected none
    of them. A corpus edit that changes this picture must not pass unnoticed."""
    rows = _corpus_waiver_entries()
    # `len(rows) == 8` and `tiers == {"WAIVED": 7, "PASS_STRUCTURAL": 1}` were
    # the corpus' size written down twice. The measurement the issue turns on
    # is not how many entries there are — it is that NOT ONE of them carries
    # ENV_UNAVAILABLE, so #216's mechanism protected none of them. That
    # sentence is true of 8 entries and of 800, and it is the one asserted.
    assert rows, "no tracked waivers-dialect entry — nothing was measured"

    tiers = {}
    for _wf, _idx, entry in rows:
        tier = (entry.get("verdict_tier") or "").strip().upper()
        tiers[tier] = tiers.get(tier, 0) + 1
    assert sum(tiers.values()) == len(rows), (tiers, len(rows))
    assert "ENV_UNAVAILABLE" not in tiers, tiers
    # The tier vocabulary is closed: a NEW tier appearing in the corpus is a
    # change to the picture this issue rests on and must not pass unnoticed.
    assert set(tiers) <= {"WAIVED", "PASS_STRUCTURAL"}, tiers
    assert tiers.get("WAIVED"), tiers


@needs_corpus
def test_every_corpus_entry_is_well_formed_so_none_is_a_rejection():
    """The dropped entries are not junk. Each carries the attestation quartet
    that makes an ENV_UNAVAILABLE waiver honourable, which is exactly why
    filing them as rejections would be the opposite lie."""
    checked = 0
    for wf, idx, entry in _corpus_waiver_entries():
        where = f"{wf.parent.name} entry {idx}"
        checked += 1
        assert isinstance(entry.get("ticket"), str) and entry["ticket"], where
        assert entry.get("review_required") is True, where
        assert isinstance(entry.get("evidence"), list) and entry["evidence"], where
        assert len((entry.get("rationale") or "").strip()) >= 40, where
        assert _we.resolve_step_name(entry.get("step")) is not None, where
    # "None of them is junk" over an empty corpus is a sentence about nothing,
    # and it was the shape this test held for as long as the loop found no
    # entry: green, and describing a population it never read.
    assert checked, ("no `waivers`-dialect entry in the corpus — this test "
                     "vouches for the entries and has vouched for none")


# ----------------------------------------------------------------------
# 2. The disclosure exists, and says the four things it has to say
# ----------------------------------------------------------------------

def test_waived_tier_entry_is_disclosed(tmp_path):
    """The defect itself: a sanctioned, ticketed entry now leaves a trace."""
    fcc, _ = _load(_project(tmp_path, _entry()))
    notes = fcc._WAIVER_NOT_BOUND_DISCLOSURES
    assert len(notes) == 1, notes
    assert notes[0].startswith("WAIVER READ, NOT BOUND"), notes[0]


def test_disclosure_names_the_entry_the_step_the_tier_and_the_ticket(tmp_path):
    """A reader must be able to go from the report back to the line in the
    file. Index, role name, resolved flow step, tier as written, ticket."""
    fcc, _ = _load(_project(tmp_path, _entry(), _entry(
        step="drc", ticket="TAPEOUT-AUTOGEN-DRC")))
    notes = fcc._WAIVER_NOT_BOUND_DISCLOSURES
    assert len(notes) == 2, notes
    assert "entry 0" in notes[0] and "'lvs'" in notes[0]
    assert "entry 1" in notes[1] and "'drc'" in notes[1]
    for note in notes:
        assert "flow step 31" in note, note
        assert "'WAIVED'" in note, note
    assert "TAPEOUT-AUTOGEN-LVS" in notes[0]
    assert "TAPEOUT-AUTOGEN-DRC" in notes[1]


def test_pass_structural_tier_is_disclosed_with_its_own_tier_text(tmp_path):
    """The corpus's second tier. The disclosure quotes the tier AS WRITTEN, so
    an unknown tier is legible rather than collapsed into "not ENV"."""
    fcc, _ = _load(_project(tmp_path, _entry(
        verdict_tier="PASS_STRUCTURAL", ticket="TAPEOUT-LVS-DEVICELEVEL")))
    notes = fcc._WAIVER_NOT_BOUND_DISCLOSURES
    assert len(notes) == 1, notes
    assert "'PASS_STRUCTURAL'" in notes[0], notes[0]


def test_disclosure_says_it_is_not_a_rejection(tmp_path):
    """Constraint 2 in the text of the message, not only in the plumbing: a
    reader must not come away believing the step lost an exemption."""
    fcc, _ = _load(_project(tmp_path, _entry()))
    note = fcc._WAIVER_NOT_BOUND_DISCLOSURES[0]
    assert "NOT a rejection" in note, note
    assert "granted nothing and refused nothing" in note, note


def test_disclosure_is_not_filed_as_a_rejection_or_an_evidence_note(tmp_path):
    """Constraint 2 in the plumbing. Three lists, three meanings: refused
    (#216), applied-but-uncorroborated (#524), read-but-not-bound (#529).
    Merging any two of them loses the distinction that makes them useful."""
    fcc, _ = _load(_project(tmp_path, _entry()))
    assert fcc._ENV_WAIVER_REJECTIONS == []
    assert fcc._ENV_WAIVER_EVIDENCE_NOTES == []
    assert len(fcc._WAIVER_NOT_BOUND_DISCLOSURES) == 1


def test_env_unavailable_entry_produces_no_unbound_disclosure(tmp_path):
    """The signal has to mean something. An entry this checker DOES bind must
    produce no disclosure at all, or every report grows noise."""
    fcc, waivers = _load(_project(tmp_path, _entry(
        verdict_tier="ENV_UNAVAILABLE")))
    assert 31 in waivers and waivers[31]["_env_unavailable"] is True
    assert fcc._WAIVER_NOT_BOUND_DISCLOSURES == []


def test_disclosure_list_is_cleared_between_loads(tmp_path):
    """Repeated calls in one process must not accumulate — the contract
    `_ENV_WAIVER_REJECTIONS` already keeps."""
    project = _project(tmp_path, _entry())
    fcc, _ = _load(project)
    fcc, _ = _load(project)
    assert len(fcc._WAIVER_NOT_BOUND_DISCLOSURES) == 1


# ----------------------------------------------------------------------
# 3. It changes NOTHING (constraint 2, measured)
# ----------------------------------------------------------------------

def test_unbound_entry_binds_no_step(tmp_path):
    fcc, waivers = _load(_project(tmp_path, _entry()))
    assert 31 not in waivers, waivers
    assert len(fcc._WAIVER_NOT_BOUND_DISCLOSURES) == 1


def test_step_verdicts_are_identical_with_and_without_the_waiver_file(tmp_path):
    """The A/B, in miniature and end-to-end: the only thing the entry may
    change is the advisory list. Same exit code, same overall verdict, same
    status in every step row."""
    with_waiver = tmp_path / "w"
    with_waiver.mkdir()
    _project(with_waiver, _entry())
    without = tmp_path / "n"
    without.mkdir()

    r_w, rep_w = _run_report(with_waiver, tmp_path / "w.json")
    r_n, rep_n = _run_report(without, tmp_path / "n.json")

    assert rep_w is not None and rep_n is not None, (r_w.stderr, r_n.stderr)
    assert r_w.returncode == r_n.returncode
    assert rep_w["overall"] == rep_n["overall"]
    assert rep_w["counts"] == rep_n["counts"]
    assert ([(s["id"], s["status"]) for s in rep_w["steps"]]
            == [(s["id"], s["status"]) for s in rep_n["steps"]])

    assert len(_disclosures(rep_w)) == 1, rep_w["advisories"]
    assert _disclosures(rep_n) == []


def test_disclosure_reaches_the_report_advisories(tmp_path):
    """Where it appears: the `Advisories:` block of the text report and the
    `advisories` array of the JSON report, beside #216's and #524's."""
    r, report = _run_report(_project(tmp_path, _entry()), tmp_path / "r.json")
    assert report is not None, r.stderr
    assert len(_disclosures(report)) == 1, report["advisories"]
    assert "WAIVER READ, NOT BOUND" in r.stdout


# ----------------------------------------------------------------------
# 4. No schema error may propagate (#519's failure mode)
# ----------------------------------------------------------------------

@pytest.mark.parametrize("tier", [7, ["WAIVED"], {"t": "WAIVED"}, 3.5, True])
def test_a_non_string_tier_does_not_delete_the_report(tmp_path, tier):
    """Against the unfixed tree this exact input printed `cannot parse …` and
    produced a ZERO-line report: `.strip()` on a non-string raised, and the
    sole handler of that block turns any exception into `SystemExit(1)`. One
    mistyped field deleted all 40+ step rows."""
    out = tmp_path / "r.json"
    r, report = _run_report(_project(tmp_path, _entry(verdict_tier=tier)), out)
    assert report is not None, (
        "no report at all — the #519 failure mode\n" + r.stdout + r.stderr)
    assert report.get("steps"), "report has no steps"
    assert "cannot parse" not in r.stderr, r.stderr


def test_a_non_string_tier_is_disclosed_by_type(tmp_path):
    """Surviving is not enough — the entry must still be visible, and the
    reason must be actionable: the field is the wrong TYPE."""
    fcc, waivers = _load(_project(tmp_path, _entry(verdict_tier=7)))
    notes = fcc._WAIVER_NOT_BOUND_DISCLOSURES
    assert len(notes) == 1, notes
    assert "of type int, not a string" in notes[0], notes[0]
    assert 31 not in waivers


def test_a_missing_tier_is_disclosed_as_missing(tmp_path):
    """The silent `continue` also swallowed an entry with no tier at all —
    indistinguishable, in the report, from no waivers.json."""
    entry = _entry()
    del entry["verdict_tier"]
    fcc, _ = _load(_project(tmp_path, entry))
    notes = fcc._WAIVER_NOT_BOUND_DISCLOSURES
    assert len(notes) == 1, notes
    assert "no `verdict_tier`" in notes[0], notes[0]


def test_a_non_object_entry_is_already_loud_in_the_normal_path(tmp_path):
    """CORRECTING THE ISSUE. It states that every `continue` in this loop other
    than the tier one was covered by #216. Two were not — but they are not
    silent either, because `waivers_schema_check` rejects both shapes with an
    ERROR before the loop ever runs, and `_load_waivers` turns that into a
    LOUD `SystemExit(1)` naming the entry. Executed, not assumed."""
    project = _project(tmp_path, "just a string", _entry())
    out = tmp_path / "r.json"
    r, report = _run_report(project, out)
    assert report is None, "schema error should stop the run, loudly"
    assert r.returncode == 1
    assert "entry-type" in r.stderr, r.stderr
    assert "entry 0" in r.stderr, r.stderr


def test_a_non_object_entry_is_disclosed_when_validation_is_unavailable(tmp_path):
    """…and the loop is still reachable without the validator. `_load_waivers`
    has an explicit ImportError fallback that loads WITHOUT schema validation,
    and on that path the non-object entry is the loop's own responsibility. It
    is disclosed rather than dropped, and it does not raise."""
    fcc, _ = _load_unvalidated(_project(tmp_path, "just a string", _entry()))
    notes = fcc._WAIVER_NOT_BOUND_DISCLOSURES
    assert len(notes) == 2, notes
    assert notes[0].startswith("WAIVER ENTRY UNREADABLE"), notes[0]
    assert "entry 0 is a str" in notes[0], notes[0]
    assert notes[1].startswith("WAIVER READ, NOT BOUND"), notes[1]


def test_an_unrecognised_step_name_is_still_disclosed(tmp_path):
    """Tier and role name can be wrong at once. The tier branch fires first, so
    its message must still tell the reader the name did not resolve rather than
    printing a confident `flow step None`."""
    fcc, _ = _load(_project(tmp_path, _entry(step="not_a_role_name")))
    note = fcc._WAIVER_NOT_BOUND_DISCLOSURES[0]
    assert "not a recognised flow role name" in note, note
    assert "flow step None" not in note, note


def test_a_superseded_entry_is_disclosed_and_the_step_stays_waived(tmp_path):
    """The loop's last silent `continue`. A `waived_steps` entry wins, which is
    correct — but a reader could not see WHICH of two entries supplied the
    rationale the report quotes. The step remains WAIVED either way."""
    (tmp_path / "waivers.json").write_text(json.dumps({
        "_schema_version": "1",
        "waived_steps": [{
            "id": 31, "reason": "hand-authored deferral for physical "
                                "verification pending the foundry deck",
            "approver": "signoff-engineer", "approved_at": "2026-01-01"}],
        "waivers": [_entry(verdict_tier="ENV_UNAVAILABLE")],
    }, indent=2))
    fcc, waivers = _load(tmp_path)
    assert 31 in waivers
    assert waivers[31]["approver"] == "signoff-engineer"
    notes = fcc._WAIVER_NOT_BOUND_DISCLOSURES
    assert len(notes) == 1, notes
    assert notes[0].startswith("WAIVER SUPERSEDED"), notes[0]
    assert "IS waived" in notes[0], notes[0]


def test_a_waivers_key_holding_a_non_list_does_not_crash(tmp_path):
    """REQUIREMENT 5, exercised. The loop takes its entries from the shared
    reader (#519), which yields nothing for a key holding a non-list instead of
    iterating a dict's KEYS as `data.get("waivers")` did. Without the validator
    to reject it first, that difference is the difference between a clean
    no-entries load and four bogus per-key disclosures."""
    (tmp_path / "waivers.json").write_text(json.dumps(
        {"_schema_version": "1", "waivers": {"step": "lvs"}}, indent=2))
    fcc, waivers = _load_unvalidated(tmp_path)
    assert 31 not in waivers
    assert fcc._WAIVER_NOT_BOUND_DISCLOSURES == []
    assert _we.entries_by_key({"waivers": {"step": "lvs"}}) == {}
    assert _we.malformed_keys({"waivers": {"step": "lvs"}}) == ["waivers"]


# ----------------------------------------------------------------------
# 5. What the other tiers are for — the claim in the disclosure, pinned
# ----------------------------------------------------------------------

def test_no_tier_value_but_env_unavailable_is_tested_anywhere(tmp_path):
    """The disclosure asserts that no gate binds a non-ENV_UNAVAILABLE tier.
    Pinned by EXECUTION at the two places that test a tier at all: this
    module's loader, and `waiver_staleness`."""
    for tier in ("WAIVED", "PASS_STRUCTURAL", "ZZZ_UNKNOWN_TIER", "PASS"):
        assert not _ws.is_env_unavailable({"verdict_tier": tier}), tier
        _fcc, waivers = _load(_project(tmp_path, _entry(verdict_tier=tier)))
        assert 31 not in waivers, tier
    assert _ws.is_env_unavailable({"verdict_tier": "ENV_UNAVAILABLE"})


def test_the_hygiene_gates_consume_the_entry_and_ignore_its_tier(tmp_path):
    """The other half of the claim, and the reason the disclosure does NOT say
    the entry is ignored: `waivers_schema_check` examines it, and examines it
    identically whatever the tier says. Run, not read."""
    def _schema_stdout(tier, _seq=[0]):
        # Index-based, not hash-based: `hash(str)` is salted per process, so a
        # hash-derived directory name is not reproducible across runs.
        _seq[0] += 1
        proj = tmp_path / f"t_{_seq[0]:02d}"
        proj.mkdir()
        _project(proj, _entry(verdict_tier=tier))
        r = _pr.run([sys.executable, str(WSC), str(proj)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        return r.returncode, r.stdout.replace(str(proj), "<P>")

    baseline = _schema_stdout("WAIVED")
    assert "Waiver count: 1" in baseline[1], baseline[1]
    for tier in ("PASS_STRUCTURAL", "ZZZ_UNKNOWN_TIER", "ENV_UNAVAILABLE"):
        assert _schema_stdout(tier) == baseline, tier


def test_the_entry_is_listed_for_a_human_by_final_report_generate(tmp_path):
    """The other name in the disclosure. `final_report_generate` is the one
    consumer that puts these entries in front of a person, so the message
    points a reader at `reports/final_summary.md` rather than leaving them to
    conclude the entry went nowhere. Executed against that module's OWN reader.

    KNOWN RESIDUAL, reported and deliberately NOT fixed here (it is a different
    file and a separately measurable blast radius): `_gather_waivers` selects
    `waived_steps` OR `waivers`, first NON-EMPTY key wins, instead of the
    shared reader's UNION — so once anything materialises a `waived_steps`
    array into the same file, these entries drop out of the summary. Sequencing
    `waivers_materialize` then `final_report_generate` on a corpus project
    reproduces it: the ticket is present in the summary in the first case and
    absent in the second."""
    import final_report_generate as frg

    _project(tmp_path, _entry())
    listed = frg._gather_waivers(tmp_path)["steps"]
    assert len(listed) == 1, listed
    assert listed[0].get("ticket") == "TAPEOUT-AUTOGEN-LVS", listed


def _tiers_the_producer_emits():
    """EXECUTE `_autogen_waivers_json` over every step status it could be handed
    and collect the `verdict_tier` values it actually writes.

    A helper, not a copy: both halves of the split below drive THIS, so the
    producer claim is made in one place and the corpus half cannot drift into
    asserting a different version of it.
    """
    import tempfile

    import phase3_one_shot_runner as p3

    emitted_tiers = set()
    with tempfile.TemporaryDirectory() as td:
        for status in ("WAIVED", "ENV_UNAVAILABLE", "PASS", "FAIL", "SKIP"):
            sub = Path(td) / status
            sub.mkdir()
            p3._autogen_waivers_json(sub, [p3.StepResult(
                "lvs", status, 0.1, "deferred to the signoff engineer",
                extras={"missing_tool": "netgen"})])
            wp = sub / "waivers.json"
            if wp.is_file():
                for e in json.loads(wp.read_text())["waivers"]:
                    emitted_tiers.add(e["verdict_tier"])
    return emitted_tiers


def test_pass_structural_is_written_by_no_producer():
    """Half one of the finding, and the half that is about the PLUGIN.

    `PASS_STRUCTURAL` is a tier the one producer of the dialect cannot emit:
    `phase3_one_shot_runner._autogen_waivers_json` copies the step STATUS into
    `verdict_tier` and only ever emits entries for WAIVED / ENV_UNAVAILABLE
    steps.

    DELIBERATELY UNMARKED, and that is the point of splitting the test. This
    claim is proved by executing the producer over a tmp_path project; it needs
    no published cell, and attaching the corpus marker to it would have switched
    off a live piece of plugin verification every time the corpus was absent —
    the blanket-skip failure mode. Only the half that reads published waivers
    below is guarded.
    """
    emitted_tiers = _tiers_the_producer_emits()
    assert emitted_tiers == {"WAIVED", "ENV_UNAVAILABLE"}, emitted_tiers
    assert "PASS_STRUCTURAL" not in emitted_tiers


@needs_corpus
def test_pass_structural_is_read_by_no_consumer_yet_sits_in_the_corpus():
    """Half two: the tier NO PRODUCER EMITS is nevertheless in the published
    tree — i.e. it got there by hand.

    Guarded, because the subject is a PUBLISHED CELL. The producer claim it
    rests on is re-established here rather than assumed, so this half is a
    complete statement on its own and does not become true-by-omission when the
    other test is the one that breaks.
    """
    assert "PASS_STRUCTURAL" not in _tiers_the_producer_emits()

    # `len(hand_authored) == 1` counted the corpus. The claim is that the tier
    # NO PRODUCER EMITS is nevertheless present in the tracked tree — i.e. it
    # got there by hand — which is a statement about existence, not about how
    # many. One is enough to make it; a hundred would make it just as well.
    hand_authored = [
        (wf.parent.name, idx) for wf, idx, e in _corpus_waiver_entries()
        if (e.get("verdict_tier") or "").upper() == "PASS_STRUCTURAL"]
    assert hand_authored, (
        "PASS_STRUCTURAL is emitted by no producer (asserted above) and now "
        "appears in no tracked waiver either — so this test no longer "
        "demonstrates the hand-authored tier it exists to name")
