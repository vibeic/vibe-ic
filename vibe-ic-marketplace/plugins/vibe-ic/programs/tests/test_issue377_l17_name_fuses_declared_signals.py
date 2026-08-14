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


E3G_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "l17_e3g_rail"

#: The report cap in the producer: `"entries": fused[:20]`. Read here so the
#: cap-awareness below states the same number the producer does.
_ENTRY_REPORT_CAP = 20


def _e3g_fixture_row(tmp_path):
    """The owned fixture, laid out as a project, audited, evidence returned."""
    import importlib
    import shutil
    g = importlib.import_module("l17_channel_catalog_consumer_contract_check")
    gd = tmp_path / "e3g" / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    shutil.copy(E3G_FIXTURE / "fusion_rail.L17_CHANNEL_CATALOG.json",
                gd / "L17_CHANNEL_CATALOG.json")
    shutil.copy(E3G_FIXTURE / "fusion_rail.L9_INTEGRATION_SPEC.json",
                gd / "L9_INTEGRATION_SPEC.json")
    findings, _ = g.audit(tmp_path / "e3g")
    fired = [f for f in findings
             if f.category == "CHANNEL_NAME_FUSES_DECLARED_SIGNALS"]
    assert len(fired) == 1, [f.category for f in findings]
    return fired[0].evidence


def test_the_rail_reports_exactly_the_entries_that_lose_something(tmp_path):
    """The rail's own truth table, over a population this test owns.

    THIS REPLACES THREE CENSUS PINS. `len(rows) == 23`, `sum(len(e)) == 62` and
    `sum(len(members_lost)) == 131` counted the published corpus, not the rail:
    each moves when anyone publishes or withdraws a cell, and PR #1028 takes all
    three to zero at once. The property those integers were standing in for is
    "the rail reports an entry exactly when the fusion LOSES a declared signal,
    and reports every member it lost" — which is stated here against
    `fixtures/l17_e3g_rail/`, where the answer is fixed by documents this test
    ships.

    The four branches, and which is which, are in the fixture's README.
    """
    ev = _e3g_fixture_row(tmp_path)
    entries = ev["entries"]
    by_name = {e["declared_name"]: e for e in entries}

    # FIRES — and on exactly these. The two silent cases below are the reason
    # this is an equality and not a `>=`.
    assert set(by_name) == {"sig_alpha / sig_beta",
                            "sig_gamma, sig_delta, sig_epsilon",
                            "sig_zeta / sig_eta"}, sorted(by_name)
    # SILENT — a group name beside BOTH its members loses nothing…
    assert "sig_theta / sig_iota" not in by_name
    # …and a string with an unreadable part is refused, not guessed at.
    assert "sig_kappa / q" not in by_name

    assert [len(by_name[n]["members_lost"]) for n in
            ("sig_alpha / sig_beta", "sig_gamma, sig_delta, sig_epsilon",
             "sig_zeta / sig_eta")] == [2, 3, 1]
    # The PARTIAL case: one member does reach a port of its own, the other
    # does not, and only the second is charged.
    partial = by_name["sig_zeta / sig_eta"]
    assert partial["members_also_emitted_separately"] == ["sig_zeta"]
    assert partial["members_lost"] == ["sig_eta"]

    assert ev["entries_reported"] == 3
    assert ev["declared_signals_without_a_port"] == 6


def test_the_reported_total_is_the_honest_count_not_the_n_minus_one_one(
        tmp_path):
    """The number a reader acts on, pinned.

    The fused port is not any member's port — a terminal named "AA_BB" is
    neither AA nor BB — so no member may be charged to it. An N-1 arithmetic
    (which is what E3b does, and what this rail was first written to do)
    under-reports by one per entry and would report ZERO for the partial cases,
    where exactly one member is missing.

    `== 131` USED TO STAND WHERE THE DISCRIMINATION IS NOW. That integer made
    the test look strong and was doing none of the work: it is the corpus'
    size, and it would have been satisfied by any arithmetic that happened to
    total 131. What decides the claim is that the honest total DIFFERS from
    what N-1 would say — asserted here as the inequality it is, so a producer
    that switched to N-1 fails even if some other corpus made the two agree.
    """
    ev = _e3g_fixture_row(tmp_path)
    entries = ev["entries"]

    honest = sum(len(e["members_lost"]) for e in entries)
    n_minus_one = sum(len(e["members_named"]) - 1 for e in entries)

    assert ev["declared_signals_without_a_port"] == honest, (
        "the reported total must be the members actually lost")
    assert honest != n_minus_one, (
        "the fixture no longer distinguishes the two arithmetics, so the "
        f"assertion above proves nothing: honest={honest} n-1={n_minus_one}")
    assert ev["declared_signals_without_a_port"] != n_minus_one

    # `entries` is capped at 20 in the report; `entries_reported` is not. They
    # agree here BECAUSE the fixture is under the cap — stated, so that a
    # fixture grown past it fails loudly instead of quietly comparing a
    # truncated list against an untruncated count.
    assert len(entries) < _ENTRY_REPORT_CAP, len(entries)
    assert ev["entries_reported"] == len(entries)


def test_the_corpus_rail_reports_every_member_it_lost_and_no_other():
    """The same property, over whatever corpus this checkout carries.

    A RELATION, NOT A CENSUS. Every clause below is true of one project on its
    own, so it says the same thing about 23 published cells, about 104, and
    about the 1 a future checkout might carry — and it says nothing at all when
    there are none, which `_need_corpus` turns into a skip rather than a lie.

    Cap-aware on purpose: `entries` is truncated at 20 and
    `declared_signals_without_a_port` is not, so the totals are compared only
    for the rows the cap did not bite. Which rows those are is asserted, not
    assumed.
    """
    _need_corpus()
    rows = _fusion_rows(with_evidence=True)
    assert rows, (
        "the rail fires on no published cell, so every clause below is "
        "vacuous — re-derive the population before trusting this test")
    uncapped = 0
    for proj, ev in rows:
        assert ev["entries_reported"] >= len(ev["entries"]), (proj, ev)
        if len(ev["entries"]) < _ENTRY_REPORT_CAP:
            uncapped += 1
            assert ev["entries_reported"] == len(ev["entries"]), (proj, ev)
            assert ev["declared_signals_without_a_port"] == sum(
                len(e["members_lost"]) for e in ev["entries"]), (proj, ev)
        for e in ev["entries"]:
            assert len(e["members_named"]) >= 2, (proj, e)
            assert e["members_lost"], (proj, e)
            assert set(e["members_lost"]).isdisjoint(
                e["members_also_emitted_separately"]), (proj, e)
            assert (len(e["members_lost"])
                    + len(e["members_also_emitted_separately"])
                    == len(e["members_named"])), (proj, e)
    assert uncapped, (
        "every reported project hit the 20-entry cap, so the total-vs-entries "
        "clause above examined nothing")


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


def _assert_consumer_agrees(proj, entries):
    """The consumer's own derivation is re-run; return how many entries it
    adjudicated, so the caller can prove the loop was not empty."""
    import importlib
    g = importlib.import_module("l17_channel_catalog_consumer_contract_check")
    c = importlib.import_module("phase2_scaffold_gen")
    gd = proj / "phase1" / "generated_docs"
    l17 = g._unwrap(g._read_json(sorted(gd.glob("L17_*.json"))[0]))
    l9 = g._unwrap(g._read_json(gd / "L9_INTEGRATION_SPEC.json"))
    emitted = {s["name"] for s in c.derive_signals(l17, l9)}
    for e in entries:
        assert e["emitted_port"] in emitted, (proj, e)
        for lost in e["members_lost"]:
            assert c._sanitize_id(lost) not in emitted, (proj, e, lost)
        for kept in e["members_also_emitted_separately"]:
            # The other half of the claim, and it was never asserted: a member
            # the rail declined to charge must really BE in the output. Without
            # it a rail that called every member "also emitted separately"
            # would report nothing and pass.
            assert c._sanitize_id(kept) in emitted, (proj, e, kept)
    return len(entries)


def test_the_fused_port_is_really_in_the_consumers_output(tmp_path):
    """ARTIFACT-FIRST. Not "the rule would fire" — the consumer's own
    derivation is re-run and the single fused port is looked up in it.

    `checked == 62` USED TO CLOSE THIS TEST. It was a non-vacuity counter
    wearing a census's clothes: the loop increments once per entry, so the
    integer restated the corpus' entry count and could only ever say "the
    corpus has not been republished". What it MEANT is "the loop was not
    empty", which is asserted here against a count derived from the same
    evidence rather than typed in — over the owned fixture, so it holds with no
    corpus at all.
    """
    ev = _e3g_fixture_row(tmp_path)
    checked = _assert_consumer_agrees(tmp_path / "e3g", ev["entries"])
    assert checked == ev["entries_reported"] > 0, (checked, ev)


def test_the_fused_port_is_in_the_consumers_output_on_the_corpus_too():
    """The same artefact-first check, over whatever corpus is present.

    Every published cell that fires the rail is adjudicated; the count is
    derived from the evidence, never typed in, so republishing changes it and
    nothing else.
    """
    _need_corpus()
    rows = _fusion_rows()
    assert rows, "the rail fires on no published cell — nothing was checked"
    checked = sum(_assert_consumer_agrees(p, e) for p, e in rows)
    assert checked == sum(len(e) for _, e in rows) > 0, checked


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
    # WHY A PROPERTY AND NOT A COUNT, measured on main before this change:
    # the pinned census drifted 21 -> 16 fired and 103 -> 101 status_nothing,
    # and running the checker AS IT STOOD BEFORE its last change (`b442b9b3`)
    # against today's corpus gave the SAME 16/101 — so the rule decided exactly
    # what it decided before and the projects underneath it moved. A census pin
    # goes red on that; the property below does not, and still fails on the
    # thing the pin was there to catch.
    assert populated_found_nothing, (
        "no published cell reports EXTRACTION_FOUND_NOTHING over a POPULATED "
        "catalog, so this test examined nothing — re-derive the population "
        "before trusting it")
    assert offenders == [], (
        "E1 fired on cells that declare a catalog the consumer reads, which is "
        f"exactly what relaxing the conjunct would do: {offenders}")
