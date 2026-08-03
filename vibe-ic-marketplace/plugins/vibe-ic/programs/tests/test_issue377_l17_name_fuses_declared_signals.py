#!/usr/bin/env python3
"""vibe-ic#377 — corpus guards for E3g CHANNEL_NAME_FUSES_DECLARED_SIGNALS.

WHAT THE RE-MEASUREMENT FOUND, AND WHAT IT REFUTED
--------------------------------------------------
The increment this rail came from was proposed as: relax E1's
`channels == 0 and global_signals == 0` conjunct, because ~64 projects were
said to build a port list out of content the producer stamped
EXTRACTION_FOUND_NOTHING. Re-measured from scratch:

  * E1 fires on 21 of 105 projects                                   CONFIRMED
  * 85 of 87 phase1_parity L17 docs carry EXTRACTION_FOUND_NOTHING   CONFIRMED
  * "~64" was 85 - 21, which subtracts a WHOLE-CORPUS count from a
    PARITY-ONLY one. 17 of the 21 E1 firings are in ic/cvdp cells and
    are disjoint from the 85. The real population is 85 - 4 = 81.      REFUTED
  * "template content that has nothing to do with the design" —
    measured false. The content is per-cell reference material for the
    cell's OWN subject, authored by that cell's own synth program.
    Only 52 of 484 distinct declared names occur in more than one
    project, and those are the common supply/management terminals that
    genuinely recur.                                                   REFUTED

So relaxing E1 would have taken the corpus to 0 PASS of 105 while asserting a
sentence the corpus contradicts. What IS defective, and what this rail
reports, is narrower and provable on disk: an entry that names SEVERAL
terminals inside one `name` string, which the consumer fuses into one port.

These guards pin the population so a loosened splitter cannot quietly grow the
rail, and a tightened one cannot quietly silence it.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = (Path(__file__).resolve().parent.parent
        / "l17_channel_catalog_consumer_contract_check.py")
REPO = Path(__file__).resolve().parents[5]

sys.path.insert(0, str(PROG.parent))


def _projects():
    """Every git-tracked published cell carrying phase1/generated_docs."""
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "benchmark-data"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return []
    seen = []
    for rel in out.stdout.split("\n"):
        if "/phase1/generated_docs/L17_" not in rel:
            continue
        proj = REPO / rel.split("/phase1/generated_docs/")[0]
        if proj not in seen:
            seen.append(proj)
    return seen


def _fusion_rows(with_evidence: bool = False):
    """(project, entries) for every project where the rail fires."""
    import importlib
    g = importlib.import_module("l17_channel_catalog_consumer_contract_check")
    rows = []
    for proj in _projects():
        findings, _ = g.audit(proj)
        for f in findings:
            if f.category == "CHANNEL_NAME_FUSES_DECLARED_SIGNALS":
                rows.append((proj, f.evidence if with_evidence
                             else f.evidence["entries"]))
    return rows


def _need_corpus():
    if not _projects():
        pytest.skip("published corpus not present in this checkout")


def test_corpus_population_of_the_rail_is_pinned():
    """23 projects / 62 entries / 69 declared signals that never reach a port.

    `entries` is truncated to 20 in the report, so the project count and the
    per-project shape are what is asserted; the totals are recomputed from the
    untruncated evidence of the projects under that cap."""
    _need_corpus()
    rows = _fusion_rows()
    assert len(rows) == 23, [p.name for p, _ in rows]
    assert sum(len(e) for _, e in rows) == 62
    assert sum(len(x["members_lost"]) for _, e in rows for x in e) == 131


def test_the_reported_total_is_the_honest_count_not_the_n_minus_one_one():
    """The number a reader acts on, pinned.

    The fused port is not any member's port — a terminal named "AA_BB" is
    neither AA nor BB — so no member may be charged to it. An N-1 arithmetic
    (which is what E3b does, and what this rail was first written to do)
    under-reports by one per entry and would report ZERO for the corpus'
    partial cases, where exactly one member is missing."""
    _need_corpus()
    rows = _fusion_rows(with_evidence=True)
    total = sum(ev["declared_signals_without_a_port"] for _, ev in rows)
    recomputed = sum(len(x["members_lost"]) for _, ev in rows
                     for x in ev["entries"])
    assert total == recomputed == 131, (total, recomputed)
    assert sum(ev["entries_reported"] for _, ev in rows) == 62


def test_the_rail_fires_only_where_the_producer_writes_prose_names():
    """The split that decides whether this is worth reporting at all.

    Every firing is a protocol-parity cell. Not one real-IC or cvdp cell
    fires — the design-facing extractor writes one identifier per entry. If a
    real-IC cell ever appears here the remedy is in that extractor, and this
    assertion is how anyone finds out."""
    _need_corpus()
    for proj, _ in _fusion_rows():
        assert "phase1_parity" in str(proj), proj


def test_every_reported_entry_actually_lost_a_declared_signal():
    """The rail must never report an entry whose members are all emitted
    anyway — a group name alongside its members is redundant, not lossy.

    A PARTIAL case is still a real one and is asserted as such: the corpus
    contains entries where one member does reach a port of its own and the
    other does not, and the one that does not is genuinely absent from the
    interface."""
    _need_corpus()
    partial = 0
    for proj, entries in _fusion_rows():
        for e in entries:
            assert len(e["members_named"]) >= 2, (proj, e)
            assert len(e["members_lost"]) >= 1, (proj, e)
            assert len(e["members_also_emitted_separately"]) \
                < len(e["members_named"]), (proj, e)
            if e["members_also_emitted_separately"]:
                partial += 1
    assert partial > 0, (
        "no partial case left in the corpus — the `>= 1` bound above is no "
        "longer exercised and this guard has gone quiet")


def test_the_fused_port_is_really_in_the_consumers_output():
    """ARTIFACT-FIRST. Not "the rule would fire" — the consumer's own
    derivation is re-run and the single fused port is looked up in it."""
    _need_corpus()
    import importlib
    g = importlib.import_module("l17_channel_catalog_consumer_contract_check")
    c = importlib.import_module("phase2_scaffold_gen")
    checked = 0
    for proj, entries in _fusion_rows():
        gd = proj / "phase1" / "generated_docs"
        l17 = g._unwrap(g._read_json(sorted(gd.glob("L17_*.json"))[0]))
        l9 = g._unwrap(g._read_json(gd / "L9_INTEGRATION_SPEC.json"))
        emitted = {s["name"] for s in c.derive_signals(l17, l9)}
        for e in entries:
            assert e["emitted_port"] in emitted, (proj, e)
            for lost in e["members_lost"]:
                assert c._sanitize_id(lost) not in emitted, (proj, e, lost)
            checked += 1
    assert checked == 62, checked


def test_e1_is_still_the_narrow_rail_the_remeasurement_left_it_as():
    """The conjunct this increment was asked to relax is deliberately intact.

    Pinned because relaxing it is a one-line edit whose blast radius —
    measured — is every remaining PASS in the corpus, on the strength of a
    sentence about unrelated-protocol template content that the corpus
    contradicts."""
    _need_corpus()
    import importlib
    g = importlib.import_module("l17_channel_catalog_consumer_contract_check")
    fired = status_nothing = populated_anyway = 0
    for proj in _projects():
        findings, info = g.audit(proj)
        if any(f.category == "TEMPLATE_WITHOUT_EXTRACTION" for f in findings):
            fired += 1
        if (info.get("extraction_status") or "") in g._STATUS_FOUND_NOTHING:
            status_nothing += 1
            if info.get("channels_declared") or \
                    info.get("global_signals_declared"):
                populated_anyway += 1
    assert fired == 21, fired
    # 102 -> 103: the corpus GAINED a project (the caravel_user_project cell
    # landed in v1.9.60), and it declares no channel catalog. The two counts
    # this test is actually about — `fired` and `populated_anyway` — did not
    # move, which is what says the relaxation is still un-relaxed. Verified on
    # origin/main BEFORE this batch touched anything: the number was already
    # 103 there, so this is corpus growth and not a regression from any change
    # here.
    #
    # A count over a growing corpus drifts by construction. It is kept as a
    # count rather than a ratio because the POINT is the two that stayed put.
    assert status_nothing == 103, status_nothing
    # The population the relaxation would have added, and the reason it was
    # not: these 81 declare a catalog the consumer really does read.
    assert populated_anyway == 81, populated_anyway
