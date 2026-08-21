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


E1_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "l17_e1_rail"

#: The E1 truth table, owned by this test. See the fixture's README.md.
_E1_EXPECTED = {
    "fires_template_without_extraction": True,
    "channels_declared": False,
    "globals_declared": False,
    "no_narrative": False,
    "status_extracted": False,
}


def _materialise_e1_cell(tmp_path, cell: str) -> Path:
    """Lay one owned fixture document out as a project the checker can audit."""
    import shutil
    proj = tmp_path / cell
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    shutil.copy(E1_FIXTURE / f"{cell}.L17_CHANNEL_CATALOG.json",
                gd / "L17_CHANNEL_CATALOG.json")
    shutil.copy(E1_FIXTURE / "shared.L9_INTEGRATION_SPEC.json",
                gd / "L9_INTEGRATION_SPEC.json")
    return proj


def test_e1_is_still_the_narrow_rail_the_remeasurement_left_it_as(tmp_path):
    """The conjunct this increment was asked to relax is deliberately intact.

    Pinned because relaxing it is a one-line edit whose blast radius —
    measured — is every remaining PASS in the corpus, on the strength of a
    sentence about unrelated-protocol template content that the corpus
    contradicts.

    THE POPULATION IS NOW ONE THIS TEST OWNS. This used to count three integers
    over every published cell under `benchmark-data/` and assert
    `fired == 21`, `status_nothing == 103`, `populated_anyway == 81`. None of
    those is a property of the rail: they are properties of the publication set.
    The #905 corpus reorganisations (`b96cdd48`, `e73601fe`) moved IC-level
    strays into their published cells, the project list went 103 -> 104 with
    different members, and the test went red at `fired == 16` with
    `l17_channel_catalog_consumer_contract_check` byte-for-byte unchanged. A
    test that is green only while nobody has republished anything is measuring
    the release schedule, and it fails for a reason its own message cannot
    explain.

    `fixtures/l17_e1_rail/` is the truth table E1 is DEFINED over — one document
    per cell — so the count below is exact, deterministic, and moves only when
    the rail moves. The two rows that carry the claim are `channels_declared`
    and `globals_declared`: dropping the `channels == 0 and global_signals == 0`
    conjunct — the edit this rail was asked for — makes E1 fire on them, and
    this test dies. That is the guard the integer 21 was standing in for.
    """
    import importlib
    g = importlib.import_module("l17_channel_catalog_consumer_contract_check")

    fired = set()
    for cell in sorted(_E1_EXPECTED):
        findings, info = g.audit(_materialise_e1_cell(tmp_path, cell))
        if any(f.category == "TEMPLATE_WITHOUT_EXTRACTION" for f in findings):
            fired.add(cell)
        # Each cell must reach the rail for the reason the table says it does;
        # a fixture that silently stopped declaring a catalog would make the
        # negative rows pass for the wrong reason.
        assert info.get("catalog_containers_refused") == [], (cell, info)

    assert fired == {c for c, want in _E1_EXPECTED.items() if want}, (
        f"E1 fired on {sorted(fired)}; the rail is defined to fire on "
        f"{sorted(c for c, w in _E1_EXPECTED.items() if w)}")


def test_e1_never_fires_on_a_published_cell_that_declares_a_catalog():
    """The same conjunct, restated over whatever corpus this checkout carries.

    A RELATION, NOT A COUNT — deliberately. The count this replaces drifted with
    every publish and told the reader nothing when it broke. What the relaxation
    would actually have done is fire E1 on cells that DO declare a catalog the
    consumer reads, and that is checkable without knowing how many there are.

    Non-vacuous by construction: the population it needs is asserted non-empty,
    so a corpus that stopped containing such cells fails loudly instead of
    passing over nothing.
    """
    _need_corpus()
    import importlib
    g = importlib.import_module("l17_channel_catalog_consumer_contract_check")
    populated_found_nothing = []
    offenders = []
    for proj in _projects():
        findings, info = g.audit(proj)
        if (info.get("extraction_status") or "") not in g._STATUS_FOUND_NOTHING:
            continue
        if not (info.get("channels_declared")
                or info.get("global_signals_declared")):
            continue
        populated_found_nothing.append(proj)
        if any(f.category == "TEMPLATE_WITHOUT_EXTRACTION" for f in findings):
            offenders.append(proj.name)
    assert populated_found_nothing, (
        "no published cell reports EXTRACTION_FOUND_NOTHING over a POPULATED "
        "catalog, so this test examined nothing — re-derive the population "
        "before trusting it")
    assert offenders == [], (
        "E1 fired on cells that declare a catalog the consumer reads, which is "
        f"exactly what relaxing the conjunct would do: {offenders}")
