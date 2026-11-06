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
from _published_corpus import corpus_tree, skip_reason  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


#: Repo root, from the plugin programs dir. The tracked corpus is READ here and
#: never written; every execution probe runs on a tmp_path project.
REPO_ROOT = PROGRAMS.parents[3]


def _corpus_dirs():
    """The two sub-trees of the PUBLISHED corpus that carry the `waivers`
    dialect, resolved at call time.

    This used to be a module-level tuple under `REPO_ROOT / "benchmark-data"`,
    and both halves of that stopped being right when the results moved to
    `vibeic/benchmark-data`:

    * the LOCATION moved, and only `corpus_tree()` knows where it is now — it
      is what honours the `VIBE_IC_BENCHMARK_DATA` pointer without requiring
      a canonical-cell population;
    * the GUARD `CORPUS_DIRS[0].is_dir()` was a directory-existence test used to
      mean "the corpus is here", and it is no longer either. The path it named
      does not exist in this checkout at all, so the skip it was attached to
      never fired for the tests that FAILED; and `benchmark-data/` itself does
      still exist here — it holds the design INPUTS — so its presence would
      have proved nothing anyway. The waiver population is under
      `protocol_parity/`, not under a canonical cell, so a cell-existence marker
      is not an applicability test for these three checks.

    Resolved per call rather than at import so that the pointer is read when the
    test runs, not when the module is loaded.
    """
    root = _corpus_root_dir()
    # Keep the historical prefix readable while following the corpus' current
    # canonical relocation.  This widens observation; it does not add an
    # accepted waiver tier or relax any entry assertion below.
    return (root / "protocol_parity", root / "evaluation/phase1_parity",
            root / "ic")

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
    root = corpus_tree()
    if root is None:
        pytest.skip(skip_reason())
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


def test_corpus_waivers_dialect_carries_no_env_unavailable_entry():
    """The measurement the whole issue turns on: every `waivers`-dialect entry
    in the corpus takes the tier `continue`, so #216's mechanism protected none
    of them. A corpus edit that changes this picture must not pass unnoticed."""
    rows = _corpus_waiver_entries()
    # `len(rows) == 8` and `tiers == {"PASS_WITH_WAIVERS": 7, "PASS_STRUCTURAL": 1}` were
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
    assert set(tiers) <= {"PASS_WITH_WAIVERS", "PASS_STRUCTURAL"}, tiers
    assert tiers.get("PASS_WITH_WAIVERS"), tiers


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















# ----------------------------------------------------------------------
# 3. It changes NOTHING (constraint 2, measured)
# ----------------------------------------------------------------------







# ----------------------------------------------------------------------
# 4. No schema error may propagate (#519's failure mode)
# ----------------------------------------------------------------------















def test_a_waivers_key_holding_a_non_list_does_not_crash(tmp_path):
    """REQUIREMENT 5, exercised. The loop takes its entries from the shared
    reader (#519), which yields nothing for a key holding a non-list instead of
    iterating a dict's KEYS as `data.get("waivers")` did. Without the validator
    to reject it first, that difference is the difference between a clean
    no-entries load and four bogus per-key disclosures."""
    (tmp_path / "waivers.json").write_text(json.dumps(
        {"_schema_version": "1", "waivers": {"step": "lvs"}}, indent=2))
    assert _we.entries_by_key({"waivers": {"step": "lvs"}}) == {}
    assert _we.malformed_keys({"waivers": {"step": "lvs"}}) == ["waivers"]


# ----------------------------------------------------------------------
# 5. What the other tiers are for — the claim in the disclosure, pinned
# ----------------------------------------------------------------------







def _tiers_the_producer_emits(field="verdict_tier"):
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
        # R-0915-85 — the five, each with the fields its word REQUIRES. A
        # NOT_MEASURED with no reason_class and a NOT_APPLICABLE with no
        # declared_by are refused at the row, so a fixture that omitted them
        # would be exercising a shape the producer cannot emit.
        for status, extra in (
                ("PASS_WITH_WAIVERS", {"attribution": "the signoff engineer"}),
                ("NOT_MEASURED", {"reason_class": "tool_absent"}),
                ("PASS", {}),
                ("FAIL", {}),
                ("NOT_APPLICABLE", {"declared_by": "L20 declares no LVS"})):
            sub = Path(td) / status
            sub.mkdir()
            p3._autogen_waivers_json(sub, [p3.StepResult(
                "lvs", status, 0.1, "deferred to the signoff engineer",
                extras={"missing_tool": "netgen"}, **extra)])
            wp = sub / "waivers.json"
            if wp.is_file():
                for e in json.loads(wp.read_text())["waivers"]:
                    emitted_tiers.add(e[field])
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
    # R-0915-85 — `verdict_tier` stays the BINDING key it always was: it is
    # not a step status and is not one of the five, because
    # `flow_compliance_check` binds ONLY `ENV_UNAVAILABLE` entries to a flow
    # step. The step's own word now travels beside it as `step_verdict`, so
    # this half of the finding is asserted on BOTH fields.
    emitted_tiers = _tiers_the_producer_emits()
    assert emitted_tiers == {"WAIVED", "ENV_UNAVAILABLE"}, emitted_tiers
    assert "PASS_STRUCTURAL" not in emitted_tiers
    assert _tiers_the_producer_emits(field="step_verdict") == {
        "PASS_WITH_WAIVERS", "NOT_MEASURED"}


def test_pass_structural_is_read_by_no_consumer_yet_sits_in_the_corpus():
    """Half two: the tier NO PRODUCER EMITS is nevertheless in the published
    tree — i.e. it got there by hand.

    Guarded inside `_corpus_root_dir`, because the subject is a published
    protocol-parity waiver population, not a canonical cell. The producer
    claim it rests on is re-established here rather than assumed, so this half
    is a complete statement on its own and does not become true-by-omission
    when the other test is the one that breaks.
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
