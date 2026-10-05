#!/usr/bin/env python3
"""vibe-ic#522 part 1 — every emitted L document records the release that
produced it, and a consumer can act on that.

WHAT THESE TESTS PIN, AND WHY EACH ONE EXISTS
=============================================
The measured defect: 0 of 2554 tracked ``generated_docs/L*.json`` carried
the plugin version that wrote them, so a document produced ~70 releases ago
was indistinguishable from a current one. Three issues were filed in one day
against such documents.

The tests fall into four groups, and only the first is about the happy path:

  (A) SEMANTICS — the stamp says the right thing and the reader can tell
      CURRENT from STALE from UNSTAMPED, with a version distance a caller
      can set its own bar against.

  (B) INERTNESS — the stamp must not become design content. This is not
      hypothetical: the first version emitted its taxonomy digest as
      ``"sha256:<hex>"`` and, measured on a two-design A/B of the real
      emitter, that value alone flipped ``ic_class`` from
      ``bus_peripheral`` to ``crypto_accelerator`` on nine documents,
      because the crypto detector harvests every string leaf of L1+L2 and
      matches ``\\bSHA[-_]?[0-9]*\\b``. Both directions are pinned: the
      value carries no algorithm token, AND the consumers that harvest or
      count document content skip the key.

  (C) WRITER CENSUS BY EXECUTION — the emitters are RUN and their output
      is read. Reading source cannot answer "does every writer stamp",
      because the writers were 86 near-identical private helpers plus ~30
      post-emit hooks in one 61k-line module. What can be answered by
      execution is answered by execution.

  (D) A NEW WRITER CANNOT BE ADDED SILENTLY — the ``*_protocol_synth.py``
      family is 86 copies of the same one-line writer, so a new protocol is
      overwhelmingly likely to arrive as a copy of a sibling. That family
      is guarded statically and exhaustively.

HONEST LIMIT OF (D), stated rather than papered over: the static guard is
exhaustive for the protocol-synth family and for the two Phase-1 tracks it
names, and the runtime gate in the runner catches any writer that CREATES a
document without a stamp. Neither catches a writer that READS a stamped
document, mutates it and writes it back without the chokepoint — but that
writer cannot make the vintage claim wrong, because the stamp it preserves
was written by the same release in the same run. Only the ``emitter`` field
(which names the LAST writer) would be inaccurate. That is stated in the
module docstring and is not tested for, because it is not expressible from
the artefact.

chip-AGNOSTIC: no design, PDK, vendor or part-number literal. The fixture
specs below describe a generic pipelined adder in technology vocabulary.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
_PLUGIN = _PROGRAMS.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import l_doc_generator_stamp as g  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

RUNNER = _PROGRAMS / "phase1_doc_one_shot_runner.py"

# A minimal, chip-AGNOSTIC design. Everything in it is technology
# vocabulary (clock, reset, bits, MHz) — no vendor, PDK or part number.
_FIXTURE_SPEC = """# Pipelined Adder

A 3-stage pipelined 8-bit adder.

Inputs: clk (1 bit) system clock, rst_n (1 bit) active-low reset,
a (8 bits), b (8 bits), valid_in (1 bit).
Outputs: sum (9 bits), valid_out (1 bit).

The clock runs at 50 MHz. Latency is 3 cycles.
"""


def _make_project(tmp_path: Path, spec: str = _FIXTURE_SPEC) -> Path:
    project = tmp_path / "design"
    (project / "input" / "docs").mkdir(parents=True)
    (project / "input" / "docs" / "spec.md").write_text(spec)
    return project


def _run_phase1(project: Path) -> subprocess.CompletedProcess:
    return _pr.run(
        [sys.executable, str(RUNNER), str(project)],
        capture_output=True, text=True)


def _emitted_docs(project: Path):
    gd = project / "phase1" / "generated_docs"
    return sorted(gd.glob("L*.json"))


# ─────────────────────────────────────────────────────────────────────
# (A) SEMANTICS
# ─────────────────────────────────────────────────────────────────────
def test_stamp_records_the_running_release_not_a_source_literal():
    """The version comes from the manifest at write time.

    The key this replaces (`emitted_by`) is wrong on 1137 corpus documents
    because it is a literal in the source; a value read from the manifest
    cannot be forgotten at bump time.
    """
    manifest = json.loads(
        (_PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    doc = g.stamp({}, "test.emitter")
    assert doc[g.STAMP_KEY]["plugin_version"] == manifest["version"]
    assert doc[g.STAMP_KEY]["plugin"] == "vibe-ic"


def test_unstamped_document_is_reported_as_unknown_vintage():
    v = g.verdict({"ic_name": "x"})
    assert v.status == "UNSTAMPED"
    assert v.stamped_version is None
    assert any("vintage unknown" in r for r in v.reasons)


def test_freshly_stamped_document_is_current():
    v = g.verdict(g.stamp({}, "test.emitter"))
    assert v.status == "CURRENT"
    assert v.drift == {"major": 0, "minor": 0, "patch": 0}
    assert v.reasons == []


def test_older_release_is_stale_and_reports_the_distance():
    doc = g.stamp({}, "test.emitter")
    doc[g.STAMP_KEY]["plugin_version"] = "1.0.35"
    v = g.verdict(doc, current_version="1.7.88")
    assert v.status == "STALE"
    assert v.drift == {"major": 0, "minor": 7, "patch": 53}
    assert "1.0.35" in v.reasons[0] and "1.7.88" in v.reasons[0]


def test_a_document_can_be_stale_relative_to_the_taxonomy_it_claims():
    """Same release, different L-doc taxonomy — still stale.

    This is the "stale relative to what it claims to describe" half: an L
    document is an instance of the taxonomy (it declares a doc_name, a
    doc_class and an applicability), so a taxonomy change invalidates the
    claim even when the version matches.
    """
    doc = g.stamp({}, "test.emitter")
    v = g.verdict(doc, current_taxonomy="ffffffffffff")
    assert v.status == "STALE"
    assert any("taxonomy" in r for r in v.reasons)


def test_newer_document_says_the_checkout_is_behind_not_the_document():
    doc = g.stamp({}, "test.emitter")
    doc[g.STAMP_KEY]["plugin_version"] = "9.9.9"
    v = g.verdict(doc, current_version="1.7.88")
    assert v.status == "NEWER"
    assert "checkout is behind" in v.reasons[0]


def test_unparseable_document_is_not_silently_clean():
    v = g.verdict(None)
    assert v.status == "UNREADABLE"


def test_an_unreadable_RUNNING_version_blocks_nothing():
    """REGRESSION (found by the full suite, not by these tests).

    The installed-plugin CACHE is a bare layout — `programs/` plus
    `agents/class_kb`, no `.claude-plugin/plugin.json` — so
    `plugin_version()` legitimately returns "" there, for the document AND
    for the running process. An earlier revision reported that as
    UNSTAMPED, and since this module is a BLOCKING gate in the runner's
    post-emit list, EVERY Phase-1 run from an installed cache failed.

    The document is stamped: a writer did go through the chokepoint, which
    is the invariant the gate protects. What is missing is the deployment's
    ability to name its own release, and a verdict over an unknown is not a
    verdict against the thing measured.
    """
    doc = g.stamp({}, "test.emitter")
    doc[g.STAMP_KEY]["plugin_version"] = ""
    v = g.verdict(doc, current_version="")
    assert v.status == "UNKNOWN_VERSION"
    assert g.exceeds(v, None) is False, (
        "a deployment that cannot name its own release must not fail the "
        "run it just produced")
    assert any("nothing is claimed" in r for r in v.reasons)


def test_an_unreadable_STAMPED_version_is_beyond_tolerance():
    """The other side of the same split: when WE can name our release and
    the DOCUMENT cannot name the one that wrote it, the document is as
    unusable for vintage as an unstamped one."""
    doc = g.stamp({}, "test.emitter")
    doc[g.STAMP_KEY]["plugin_version"] = ""
    v = g.verdict(doc, current_version="1.7.90")
    assert v.status == "UNKNOWN_VERSION"
    assert g.exceeds(v, None) is True
    assert g.exceeds(v, 99) is True


def test_a_missing_stamp_still_fails_even_with_no_readable_version():
    """The relaxation above must not weaken the invariant the gate exists
    for: a document with NO stamp is a writer that escaped the chokepoint,
    whatever the deployment can or cannot say about its own version."""
    v = g.verdict({"ic_name": "x"}, current_version="")
    assert v.status == "UNSTAMPED"
    assert g.exceeds(v, None) is True


@pytest.mark.parametrize("raw,want", [
    ("1.7.88", (1, 7, 88)),
    ("v1.7.88", (1, 7, 88)),
    (" 1.7.88 ", (1, 7, 88)),
    ("1.7.88-rc1", (1, 7, 88)),
    ("1.7", None),
    ("", None),
    (None, None),
    (17.88, None),
])
def test_parse_version(raw, want):
    assert g.parse_version(raw) == want


def test_drift_budget_tolerates_a_near_release_but_never_a_taxonomy_change():
    """A caller sets its own bar — except on the taxonomy, where there is
    no bar to set: the document is not an instance of the same contract."""
    near = g.stamp({}, "e")
    near[g.STAMP_KEY]["plugin_version"] = "1.6.10"
    v_near = g.verdict(near, current_version="1.7.88",
                       current_taxonomy=near[g.STAMP_KEY][
                           "l_doc_taxonomy_digest"])
    assert v_near.status == "STALE"
    assert g.exceeds(v_near, None) is True        # strict
    assert g.exceeds(v_near, 1) is False          # within 1 minor family
    assert g.exceeds(v_near, 0) is True

    far = g.stamp({}, "e")
    far[g.STAMP_KEY]["plugin_version"] = "0.9.0"
    v_far = g.verdict(far, current_version="1.7.88")
    assert g.exceeds(v_far, 99) is True           # major change: never OK

    taxo = g.stamp({}, "e")
    v_taxo = g.verdict(taxo, current_taxonomy="ffffffffffff")
    assert g.exceeds(v_taxo, 99) is True          # taxonomy: never OK


def test_taxonomy_digest_tracks_the_contract_not_the_prose():
    """Adding an L document changes the digest; rewording one does not.

    A digest over the source file would invalidate 2554 documents every
    time a comment was edited, which is how a staleness signal becomes
    noise everybody learns to ignore.
    """
    import l_doc_taxonomy as tax
    base, n = g.taxonomy_digest()
    assert base and n == len(tax.L_DOCS_V2)

    original = tax.L_DOCS_V2
    try:
        # prose-only edit: same codes, same filenames, new title/description
        tax.L_DOCS_V2 = tuple(
            tax.LDocSpec(s.code, s.full_name, s.title + " (reworded)",
                         "a completely different description")
            for s in original)
        assert g.taxonomy_digest()[0] == base, (
            "a wording change must NOT invalidate the corpus")
        # structural edit: one more document in the set
        tax.L_DOCS_V2 = original + (
            tax.LDocSpec("L99", "L99_NEW", "New", "New layer"),)
        assert g.taxonomy_digest()[0] != base, (
            "adding an L document MUST change the digest")
        assert g.taxonomy_digest()[1] == n + 1
    finally:
        tax.L_DOCS_V2 = original
    assert g.taxonomy_digest()[0] == base


# ─────────────────────────────────────────────────────────────────────
# (B) INERTNESS — the stamp must not read as design content
# ─────────────────────────────────────────────────────────────────────
def test_stamp_carries_no_algorithm_token():
    """REGRESSION. `"sha256:<hex>"` in the stamp made nine documents
    classify as a crypto accelerator. Nothing in the stamp may name an
    algorithm the crypto detector recognises."""
    from ic_class_profile import _CRYPTO_FEATURES
    blob = json.dumps(g.stamp({}, "test.emitter")[g.STAMP_KEY])
    for name, pat in _CRYPTO_FEATURES:
        assert not pat.search(blob), (
            f"stamp value matches the {name} crypto feature: {blob}")


def test_stamp_carries_no_absolute_path():
    """An L document is diffed across checkouts; the stamp must mean the
    same thing on every machine."""
    from l_doc_path_portability_check import absolute_path_reason
    for value in g.stamp({}, "test.emitter")[g.STAMP_KEY].values():
        if isinstance(value, str):
            assert absolute_path_reason(value) is None, value


def test_ic_class_classification_is_unchanged_by_the_stamp():
    """The consumer-side half of the same regression, driven through the
    real classifier rather than asserted about its source."""
    from ic_class_profile import _harvest_strings
    payload = {"ic_name": "widget", "summary": "a register-mapped block"}
    plain: list = []
    _harvest_strings(payload, plain)
    adversarial = dict(payload)
    adversarial[g.STAMP_KEY] = {
        "plugin": "vibe-ic", "plugin_version": "1.7.88",
        # the exact shape that caused the flip, kept here on purpose
        "l_doc_taxonomy_digest": "sha256:deadbeefcafe",
        "l_doc_taxonomy_docs": 28, "emitter": "m.f",
    }
    stamped: list = []
    _harvest_strings(adversarial, stamped)
    assert plain == stamped, (
        "the classifier harvested the emitter's own bookkeeping as design "
        "content")


def test_unique_content_gate_scores_the_same_with_and_without_the_stamp(
        tmp_path):
    """The stamp is identical in every document of a run by construction,
    so counting it would raise every pair's Jaccard score uniformly and
    could push a thin pair of N/A stubs over the 0.70 threshold for a
    reason unrelated to what they say."""
    from l_doc_unique_content_check import _doc_tokens
    body = {"applicability": "N/A", "rationale": "no analog interface",
            "ic_class": "digital_arithmetic_primitive"}
    plain = tmp_path / "L5_PLAIN.json"
    plain.write_text(json.dumps(body))
    stamped = tmp_path / "L5_STAMPED.json"
    g.dump(stamped, dict(body), "test.emitter")
    assert _doc_tokens(plain) == _doc_tokens(stamped)


def test_typed_field_count_is_unchanged_by_the_stamp():
    """A key present on EVERY document must not lift every layer's tally by
    one and hand a thin document a floor it did not earn."""
    from l_doc_structured_field_count_check import _count_typed_fields
    body = {"ic_name": "widget", "pin_table": [{"name": "clk"}],
            "electrical_specs": {"vdd": "1.8 V"}}
    before = _count_typed_fields(body)
    after = _count_typed_fields(g.stamp(dict(body), "test.emitter"))
    assert before == after


# ─────────────────────────────────────────────────────────────────────
# (C) WRITER CENSUS BY EXECUTION
# ─────────────────────────────────────────────────────────────────────
def test_every_document_the_canonical_entry_emits_is_stamped_current(
        tmp_path):
    """Run the real Phase-1 doc entry and READ what it wrote.

    This is the census that source-reading cannot give: whichever of the
    ~120 write sites fired for this design, every file they left behind
    must carry a current stamp.
    """
    project = _make_project(tmp_path)
    cp = _run_phase1(project)
    assert cp.returncode == 0, cp.stdout[-3000:] + cp.stderr[-3000:]

    docs = _emitted_docs(project)
    assert len(docs) >= 10, (
        f"probe observed only {len(docs)} L documents — a census over "
        f"nothing is not a census")
    unstamped = []
    for p in docs:
        v = g.verdict(json.loads(p.read_text()))
        if v.status != "CURRENT":
            unstamped.append((p.name, v.status, v.reasons))
    assert not unstamped, unstamped


def test_the_emitter_field_names_more_than_one_real_writer(tmp_path):
    """Non-vacuity guard for the census above.

    If `emitter` were a constant the census would pass while telling us
    nothing. The runner's L docs are written by a chokepoint AND rewritten
    by a series of post-emit hooks, so a real run must show several
    distinct last-writers, each an importable name in this tree.
    """
    project = _make_project(tmp_path)
    assert _run_phase1(project).returncode == 0
    emitters = {
        json.loads(p.read_text())[g.STAMP_KEY]["emitter"]
        for p in _emitted_docs(project)
    }
    assert len(emitters) >= 2, emitters
    for e in emitters:
        module, _, func = e.rpartition(".")
        assert module and func, e
        assert (_PROGRAMS / f"{module}.py").is_file() \
            or (_PLUGIN / "tools" / "phase1_engine" / f"{module}.py").is_file(), \
            f"emitter names a module that is not in this tree: {e}"


def test_the_gate_inside_the_canonical_entry_reports_on_every_run(tmp_path):
    """The gate is wired, not merely available."""
    project = _make_project(tmp_path)
    cp = _run_phase1(project)
    assert "l_doc_generator_stamp" in cp.stdout, cp.stdout[-2000:]
    reports = sorted(
        (project / "reports").rglob("l_doc_generator_stamp.json"))
    assert reports, "the gate did not write its report"
    report = reports[0]
    data = json.loads(report.read_text())
    assert data["verdict"] == "PASS"
    assert data["documents_read"] == len(_emitted_docs(project))


def test_run_to_run_output_is_byte_identical(tmp_path):
    """The stamp introduced no wall-clock field.

    A timestamp would make every regeneration of the published corpus a
    2554-file diff, which is precisely the property that makes a
    regeneration auditable.
    """
    a = _make_project(tmp_path / "a")
    b = _make_project(tmp_path / "b")
    assert _run_phase1(a).returncode == 0
    assert _run_phase1(b).returncode == 0
    da = {p.name: p.read_bytes() for p in _emitted_docs(a)}
    db = {p.name: p.read_bytes() for p in _emitted_docs(b)}
    assert set(da) == set(db)
    differing = [n for n in da if da[n] != db[n]]
    assert not differing, differing


_TRACER = '''
import builtins, json, os, pathlib, re, traceback
_LOG = os.environ["LDOC_WRITE_LOG"]
_TARGET = re.compile(r"generated_docs[/\\\\][^/\\\\]+\\.json$")
_orig = pathlib.Path.write_text


def _wt(self, *a, **k):
    try:
        s = os.fspath(self)
    except Exception:
        s = ""
    if isinstance(s, str) and _TARGET.search(s):
        frames = [f"{fr.filename}:{fr.name}"
                  for fr in traceback.extract_stack()[:-1]]
        with open(_LOG, "a") as fh:
            fh.write(json.dumps({"path": s, "frames": frames}) + "\\n")
    return _orig(self, *a, **k)


pathlib.Path.write_text = _wt
'''


def test_no_l_document_write_escapes_the_chokepoint(tmp_path):
    """The invariant, proved by execution rather than by a source scan.

    Every ``Path.write_text`` whose target is a ``generated_docs/*.json`` is
    traced during a real run, and its call stack must contain
    ``l_doc_generator_stamp.dump``.

    This is the test that a static scan cannot replace, and the reason is
    measured: a first pass converted the 26 write sites a dataflow scan
    could resolve, the suite went green, and this probe then found 13
    further writes through local names the scan could not follow
    (``l1_path = gd / 'L1_DATASHEET.json'`` is two hops from the marker).
    Each of them read a stamped document and wrote it back, so every file
    on disk still carried a stamp and every other test here still passed.
    """
    site = tmp_path / "tracer"
    site.mkdir()
    (site / "sitecustomize.py").write_text(_TRACER)
    log = tmp_path / "writes.jsonl"

    project = _make_project(tmp_path)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(site) + os.pathsep + env.get("PYTHONPATH", "")
    env["LDOC_WRITE_LOG"] = str(log)
    cp = _pr.run([sys.executable, str(RUNNER), str(project)],
                        capture_output=True, text=True, env=env)
    assert cp.returncode == 0, cp.stdout[-2000:] + cp.stderr[-2000:]
    assert log.is_file(), (
        "the probe recorded no write at all — it is not observing the "
        "runner, so a green here would mean nothing")

    events = [json.loads(ln) for ln in log.read_text().splitlines() if ln]
    assert len(events) >= 10, f"only {len(events)} writes observed"
    bypass = []
    for e in events:
        if not any(f.endswith("l_doc_generator_stamp.py:dump")
                   for f in e["frames"]):
            caller = next((f for f in reversed(e["frames"])
                           if "/programs/" in f or "/tools/" in f), "?")
            bypass.append((Path(e["path"]).name, caller))
    assert not bypass, (
        f"{len(bypass)} L-document write(s) bypassed the chokepoint: "
        f"{sorted(set(bypass))}")


def test_post_process_na_stub_and_skeleton_paths_stamp(tmp_path):
    """`phase1_post_process` builds documents FROM SCRATCH (na_stub /
    skeleton), so it is the writer class that produces an unstamped file
    when it bypasses the chokepoint — the one the runtime gate exists to
    catch."""
    import phase1_post_process as pp
    docs_dir = tmp_path / "phase1" / "generated_docs"
    docs_dir.mkdir(parents=True)
    result = pp.post_process(tmp_path, "bus_interconnect_protocol")
    assert result  # something was produced
    written = sorted(docs_dir.glob("L*.json"))
    assert written, "post_process wrote no L document — nothing was tested"
    for p in written:
        assert g.verdict(json.loads(p.read_text())).status == "CURRENT", p.name


def test_a_protocol_synth_overlay_stamps_what_it_rewrites(tmp_path):
    """One member of the 86-module family, driven for real."""
    import spi_protocol_synth as synth
    gd = tmp_path / "generated_docs"
    gd.mkdir(parents=True)
    for name in ("L1_DATASHEET", "L2_FRS", "L3_CMD_PROTOCOL",
                 "L8_RTL_CONSTANTS", "L9_INTEGRATION_SPEC"):
        (gd / f"{name}.json").write_text(json.dumps({"ic_name": "widget"}))
    synth.apply_spi_synth(gd, True, "widget")
    touched = [p for p in sorted(gd.glob("L*.json"))
               if g.STAMP_KEY in json.loads(p.read_text())]
    assert touched, "the overlay rewrote nothing — nothing was tested"
    for p in touched:
        assert g.verdict(json.loads(p.read_text())).status == "CURRENT"


def test_the_other_phase1_track_stamps_too(tmp_path):
    """`tools/phase1_engine` renders the same artefact class from a fact
    graph. A stamp on one track and not the other makes the ABSENCE of a
    stamp ambiguous, which is worse than no stamp at all."""
    # Imported through `tools.` exactly as that package's own tests do. A
    # second import path for the same file would give the interpreter two
    # module objects for one module, and a suite that half-imports each is
    # a test-order-dependent suite.
    if str(_PLUGIN) not in sys.path:
        sys.path.insert(0, str(_PLUGIN))
    from tools.phase1_engine.render import render_layers
    from tools.phase1_engine.schema import FactGraph, Fact, Provenance

    graph = FactGraph(ic_name="widget", class_path="unknown_protocol_class")
    prov = Provenance(source="user_stated", origin="spec.md")
    graph.facts.append(Fact(path="L1.overview.purpose",
                            value="an 8-bit adder", views=["L1"],
                            provenance=prov))
    graph.facts.append(Fact(path="L9.top_module", value="adder",
                            views=["L9"], provenance=prov))
    out = tmp_path / "generated_docs"
    written = render_layers(graph, out)
    assert written, "render_layers wrote nothing — nothing was tested"
    for path in written.values():
        assert g.verdict(json.loads(path.read_text())).status == "CURRENT", \
            path


# ─────────────────────────────────────────────────────────────────────
# (D) A NEW WRITER CANNOT BE ADDED SILENTLY
# ─────────────────────────────────────────────────────────────────────
_RAW_WRITE = 'p.write_text(json.dumps(d, indent=2, ensure_ascii=False)'


def test_every_protocol_synth_routes_through_the_chokepoint():
    """The 86 `*_protocol_synth.py` modules are near-identical copies of
    one private one-line writer, so the likeliest way a new unstamped
    writer arrives is a new protocol copied from a sibling. Exhaustive by
    construction: the whole family is enumerated from disk, and the
    denominator is asserted so a rename cannot make this vacuous."""
    family = sorted(_PROGRAMS.glob("*_protocol_synth.py"))
    assert len(family) >= 80, (
        f"only {len(family)} protocol-synth modules found — the glob no "
        f"longer matches the family this test exists to cover")
    offenders = []
    for f in family:
        text = f.read_text()
        if "generated_docs" not in text and "_write" not in text:
            continue
        if "l_doc_generator_stamp" not in text:
            offenders.append((f.name, "does not import the chokepoint"))
        if _RAW_WRITE in text:
            offenders.append((f.name, "still serialises an L doc directly"))
    assert not offenders, offenders


def test_the_phase1_writers_named_in_the_docstring_route_through_it():
    """The non-family writers, named so a reader can check the list against
    the census in the commit message rather than trusting a glob."""
    for rel in ("programs/phase1_doc_one_shot_runner.py",
                "programs/phase1_one_shot_runner.py",
                "programs/phase1_post_process.py",
                "programs/phase1_protocol_spec_extract.py",
                "programs/l22_coverage_goal_emit.py",
                "tools/phase1_engine/render.py",
                "tools/phase1_engine/cli.py"):
        text = (_PLUGIN / rel).read_text()
        assert "l_doc_generator_stamp" in text or "_stamp" in text, rel


def test_the_stamp_is_metadata_to_every_consumer_that_classifies_keys():
    """Each consumer's OWN predicate is exercised, not a membership list.

    Written this way after a membership-list version of this test asserted
    a requirement that was not real: `l18_interconnect_topology_factuality
    _check` already classifies any underscore-prefixed key as envelope BY
    SHAPE, so adding the stamp to its name list changed nothing and the
    test was pinning decoration. Two of the six consumers examined were in
    that position; the four below were measured to change their answer.
    """
    K = g.STAMP_KEY
    stamp = g.stamp({}, "m.f")[K]

    # (1) ic_class classification — string harvest must not see the stamp.
    from ic_class_profile import _harvest_strings
    body = {"ic_name": "widget"}
    a, b = [], []
    _harvest_strings(body, a)
    _harvest_strings(dict(body, **{K: stamp}), b)
    assert a == b, "ic_class harvest reads the stamp as design text"

    # (2)+(3) L25 / L26 "is anything here beyond metadata" — an N/A stub
    # must still look empty.
    import l25_reliability_envelope_actionable_check as l25
    import l26_mechanical_applicability_derived_check as l26
    stub = {"doc_name": "X", "applicability": "N/A", "rationale": "none",
            "extraction_status": "NOT_APPLICABLE"}
    for mod in (l25, l26):
        payload = {k: v for k, v in dict(stub, **{K: stamp}).items()
                   if k not in mod._META_KEYS}
        assert payload == {}, (
            f"{mod.__name__} sees the stamp as content on an N/A stub: "
            f"{payload}")

    # (4) parity diff — the stamp must not be counted as a divergence.
    import l_doc_parity_diff as pd
    assert K in pd._IGNORED_ENVELOPE_KEY_PREFIXES, (
        "the parity comparator would report a HALLUCINATED fact on every "
        "document, since no agent extractor emits an emitter's version "
        "record")

    # (5) L18 — covered BY SHAPE, and pinned so the shape rule cannot be
    # removed without this failing.
    import l18_interconnect_topology_factuality_check as l18
    assert l18._is_envelope(K), (
        "L18 no longer classifies underscore-prefixed keys as envelope")


def test_gate_fails_on_an_unstamped_corpus_and_passes_on_a_stamped_one(
        tmp_path):
    """The CLI a reader runs before quoting a published document."""
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps({"ic_name": "widget"}))
    cp = subprocess.run(
        [sys.executable, str(_PROGRAMS / "l_doc_generator_stamp.py"),
         str(tmp_path)], capture_output=True, text=True)
    assert cp.returncode == 1, cp.stdout
    assert "UNSTAMPED" in cp.stdout

    # --allow-unstamped is the transition switch: report, do not fail.
    cp = subprocess.run(
        [sys.executable, str(_PROGRAMS / "l_doc_generator_stamp.py"),
         str(tmp_path), "--allow-unstamped"], capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout

    g.dump(gd / "L1_DATASHEET.json", {"ic_name": "widget"}, "test.emitter")
    cp = subprocess.run(
        [sys.executable, str(_PROGRAMS / "l_doc_generator_stamp.py"),
         str(tmp_path)], capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout
    assert "CURRENT=1" in cp.stdout


def test_gate_accepts_direct_generated_docs_root(tmp_path):
    """The canonical handoff directory is also a valid CLI root."""
    generated = tmp_path / "generated_docs"
    generated.mkdir(parents=True)
    g.dump(generated / "L1_DATASHEET.json", {"ic_name": "widget"},
           "test.emitter")
    cp = subprocess.run(
        [sys.executable, str(_PROGRAMS / "l_doc_generator_stamp.py"),
         str(generated)], capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout
    assert "CURRENT=1" in cp.stdout


def test_gate_over_an_empty_root_is_vacuous_not_a_pass(tmp_path):
    """A green over nothing is indistinguishable from a wrong root."""
    cp = subprocess.run(
        [sys.executable, str(_PROGRAMS / "l_doc_generator_stamp.py"),
         str(tmp_path)], capture_output=True, text=True)
    assert cp.returncode == 2
    assert "VACUOUS" in cp.stdout


def test_project_scan_ignores_nested_source_checkout(tmp_path):
    """A project gate reads its own Phase-1 handoff only.

    The project may carry a source checkout for reproducibility. Its checked-in
    fixtures are inputs to the test harness, not documents emitted by this
    project, so they must not change the gate denominator or verdict.
    """
    from _hostpaths import require_repo

    project = tmp_path / "design"
    generated = project / "phase1" / "generated_docs"
    generated.mkdir(parents=True)
    g.dump(generated / "L1_DATASHEET.json", {"ic_name": "widget"},
           "test.emitter")

    fixture_root = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
        "tests", "fixtures")
    fixture = next(fixture_root.rglob("phase1/generated_docs/L*.json"))
    nested = project / "source" / "vibe-ic-marketplace" / "plugins" \
        / "vibe-ic" / "programs" / "tests" / "fixtures" \
        / fixture.relative_to(fixture_root)
    nested.parent.mkdir(parents=True)
    shutil.copy2(fixture, nested)
    phase1_fixture = project / "phase1" / "input-derived" \
        / "generated_docs" / "L2_FRS.json"
    phase1_fixture.parent.mkdir(parents=True)
    phase1_fixture.write_text(json.dumps({"ic_name": "fixture"}))

    result = g.scan_tree(project)
    assert result["documents_read"] == 1
    assert result["counts"] == {"CURRENT": 1}
    assert result["offending"] == []
    assert result["verdict"] == "PASS"


def test_project_scope_with_missing_handoff_fails_closed(tmp_path):
    """A malformed project does not fall back to nested fixture documents."""
    project = tmp_path / "design"
    (project / "phase1").mkdir(parents=True)
    nested = project / "source" / "fixture" / "phase1" \
        / "generated_docs" / "L1_DATASHEET.json"
    nested.parent.mkdir(parents=True)
    nested.write_text(json.dumps({"ic_name": "fixture"}))

    result = g.scan_tree(project)
    assert result["documents_read"] == 0
    assert result["offending"] == []
    assert result["verdict"] == "VACUOUS"


def test_project_scan_ignores_nested_archive_generated_docs(tmp_path):
    """The canonical project handoff is direct-only, even under phase1/."""
    project = tmp_path / "design"
    generated = project / "phase1" / "generated_docs"
    generated.mkdir(parents=True)
    g.dump(generated / "L1_DATASHEET.json", {"ic_name": "widget"},
           "test.emitter")
    nested = (project / "phase1" / "archive" / "source" / "phase1" /
              "generated_docs")
    nested.mkdir(parents=True)
    nested.joinpath("L2_FRS.json").write_text(
        json.dumps({"ic_name": "fixture"}))

    result = g.scan_tree(project)
    assert result["documents_read"] == 1
    assert result["counts"] == {"CURRENT": 1}
    assert result["verdict"] == "PASS"


def test_legacy_project_generated_docs_is_direct_only(tmp_path):
    """Older project roots keep their legal generated_docs handoff."""
    project = tmp_path / "design"
    generated = project / "generated_docs"
    generated.mkdir(parents=True)
    g.dump(generated / "L1_DATASHEET.json", {"ic_name": "widget"},
           "test.emitter")
    nested = project / "source" / "fixture" / "generated_docs"
    nested.mkdir(parents=True)
    nested.joinpath("L2_FRS.json").write_text(
        json.dumps({"ic_name": "fixture"}))

    result = g.scan_tree(project)
    assert result["documents_read"] == 1
    assert result["counts"] == {"CURRENT": 1}
    assert result["verdict"] == "PASS"


def test_empty_phase1_prefers_valid_legacy_handoff(tmp_path):
    """An empty phase1 marker does not hide a valid legacy handoff."""
    project = tmp_path / "design"
    (project / "phase1").mkdir(parents=True)
    legacy = project / "generated_docs"
    legacy.mkdir(parents=True)
    g.dump(legacy / "L1_DATASHEET.json", {"ic_name": "legacy"},
           "test.emitter")

    assert g._canonical_scan_root(project) == legacy
    result = g.scan_tree(project)
    assert result["documents_read"] == 1
    assert result["counts"] == {"CURRENT": 1}
    assert result["verdict"] == "PASS"


def test_empty_phase1_generated_docs_prefers_valid_legacy_handoff(tmp_path):
    """An empty canonical handoff directory does not hide legacy docs."""
    project = tmp_path / "design"
    (project / "phase1" / "generated_docs").mkdir(parents=True)
    legacy = project / "generated_docs"
    legacy.mkdir(parents=True)
    g.dump(legacy / "L1_DATASHEET.json", {"ic_name": "legacy"},
           "test.emitter")

    assert g._canonical_scan_root(project) == legacy
    result = g.scan_tree(project)
    assert result["documents_read"] == 1
    assert result["counts"] == {"CURRENT": 1}
    assert result["verdict"] == "PASS"


def test_direct_generated_docs_root_does_not_recurse_into_siblings(tmp_path):
    """A caller naming generated_docs gets exactly that handoff."""
    generated = tmp_path / "generated_docs"
    generated.mkdir(parents=True)
    g.dump(generated / "L1_DATASHEET.json", {"ic_name": "widget"},
           "test.emitter")
    nested = generated / "archive" / "generated_docs"
    nested.mkdir(parents=True)
    nested.joinpath("L2_FRS.json").write_text(
        json.dumps({"ic_name": "fixture"}))

    result = g.scan_tree(generated)
    assert result["documents_read"] == 1
    assert result["counts"] == {"CURRENT": 1}
    assert result["verdict"] == "PASS"


def test_symlinked_canonical_handoff_fails_closed(tmp_path):
    """A project cannot silently import L docs from an external symlink."""
    project = tmp_path / "design"
    (project / "phase1").mkdir(parents=True)
    external = tmp_path / "external" / "generated_docs"
    external.mkdir(parents=True)
    g.dump(external / "L1_DATASHEET.json", {"ic_name": "external"},
           "test.emitter")
    (project / "phase1" / "generated_docs").symlink_to(
        external, target_is_directory=True)

    result = g.scan_tree(project)
    assert result["documents_read"] == 0
    assert result["verdict"] == "VACUOUS"

    cp = subprocess.run(
        [sys.executable, str(_PROGRAMS / "l_doc_generator_stamp.py"),
         str(project)], capture_output=True, text=True)
    assert cp.returncode == 2, cp.stdout
    assert "VACUOUS" in cp.stdout


def test_empty_canonical_phase1_handoff_is_vacuous_at_cli(tmp_path):
    """An empty project handoff cannot fall through to nested fixtures."""
    project = tmp_path / "design"
    (project / "phase1").mkdir(parents=True)
    nested = project / "source" / "fixture" / "phase1" / "generated_docs"
    nested.mkdir(parents=True)
    nested.joinpath("L1_DATASHEET.json").write_text(
        json.dumps({"ic_name": "fixture"}))

    cp = subprocess.run(
        [sys.executable, str(_PROGRAMS / "l_doc_generator_stamp.py"),
         str(project)], capture_output=True, text=True)
    assert cp.returncode == 2, cp.stdout
    assert "VACUOUS" in cp.stdout


def test_root_without_project_handoff_keeps_recursive_corpus_scan(tmp_path):
    """Published corpus roots still census nested design handoffs."""
    corpus = tmp_path / "corpus"
    first = corpus / "design_a" / "generated_docs"
    second = corpus / "design_b" / "generated_docs"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    g.dump(first / "L1_DATASHEET.json", {"ic_name": "a"}, "test.emitter")
    g.dump(second / "L1_DATASHEET.json", {"ic_name": "b"}, "test.emitter")

    result = g.scan_tree(corpus, scope="corpus")
    assert result["documents_read"] == 2
    assert result["counts"] == {"CURRENT": 2}
    assert result["verdict"] == "PASS"


def test_empty_legacy_handoff_does_not_borrow_nested_fixture(tmp_path):
    """An empty legacy project handoff is VACUOUS, never a corpus PASS."""
    project = tmp_path / "design"
    (project / "generated_docs").mkdir(parents=True)
    nested = project / "source" / "fixture" / "phase1" / "generated_docs"
    nested.mkdir(parents=True)
    nested.joinpath("L1_DATASHEET.json").write_text(
        json.dumps({"ic_name": "fixture"}))

    result = g.scan_tree(project)
    assert result["documents_read"] == 0
    assert result["verdict"] == "VACUOUS"


def test_corpus_scope_does_not_treat_phase1_design_as_project(tmp_path):
    """Corpus mode remains recursive even when a child design is named phase1."""
    corpus = tmp_path / "corpus"
    first = corpus / "phase1" / "v1_x" / "phase1" / "generated_docs"
    second = corpus / "other" / "v1_y" / "phase1" / "generated_docs"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    g.dump(first / "L1_DATASHEET.json", {"ic_name": "a"}, "test.emitter")
    g.dump(second / "L1_DATASHEET.json", {"ic_name": "b"}, "test.emitter")

    result = g.scan_tree(corpus, scope="corpus")
    assert result["documents_read"] == 2
    assert result["scope"] == "corpus"
    assert result["verdict"] == "PASS"


def test_symlinked_phase1_does_not_fall_back_to_legacy(tmp_path):
    """A canonical symlink is VACUOUS even when legacy docs exist."""
    project = tmp_path / "design"
    external = tmp_path / "external" / "phase1"
    external.mkdir(parents=True)
    (project).mkdir(parents=True)
    (project / "phase1").symlink_to(external, target_is_directory=True)
    legacy = project / "generated_docs"
    legacy.mkdir(parents=True)
    g.dump(legacy / "L1_DATASHEET.json", {"ic_name": "legacy"},
           "test.emitter")

    result = g.scan_tree(project)
    assert result["documents_read"] == 0
    assert result["verdict"] == "VACUOUS"


def test_corpus_scope_recurses_when_corpus_basename_is_generated_docs(tmp_path):
    """Corpus scope does not let its root basename disable recursion."""
    corpus = tmp_path / "generated_docs"
    first = corpus / "design_a" / "generated_docs"
    second = corpus / "design_b" / "phase1" / "generated_docs"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    g.dump(first / "L1_DATASHEET.json", {"ic_name": "a"}, "test.emitter")
    g.dump(second / "L1_DATASHEET.json", {"ic_name": "b"}, "test.emitter")

    result = g.scan_tree(corpus, scope="corpus")
    assert result["documents_read"] == 2
    assert result["verdict"] == "PASS"


def test_corpus_scope_includes_direct_docs_when_root_is_generated_docs(tmp_path):
    """Recursive corpus scope includes the root handoff and nested designs."""
    corpus = tmp_path / "generated_docs"
    nested = corpus / "design_a" / "generated_docs"
    nested.mkdir(parents=True)
    g.dump(corpus / "L1_DATASHEET.json", {"ic_name": "root"}, "test.emitter")
    g.dump(nested / "L1_DATASHEET.json", {"ic_name": "nested"}, "test.emitter")

    result = g.scan_tree(corpus, scope="corpus")
    assert result["documents_read"] == 2
    assert result["verdict"] == "PASS"


def test_phase1_doc_runner_blocks_stamp_rc2_as_undetermined():
    """The canonical Phase-1 gate loop must not discard rc=2."""
    import phase1_doc_one_shot_runner as runner

    assert runner._classify_semantic_gate_rc(
        "l_doc_generator_stamp", 2) == "UNDETERMINED"
    assert runner._classify_semantic_gate_rc(
        "l_doc_generator_stamp", 1) == "FAIL"
    assert runner._classify_semantic_gate_rc(
        "l1_pin_bus_width_actionable_check", 2) == ""


def test_emitter_is_derived_from_the_live_frame_not_a_literal(tmp_path):
    """The failure mode being replaced: `emitted_by` says v0.1.51 on
    documents written at v1.7.x because it is typed into the source. A
    value read off the call frame cannot drift from the code."""
    def a_named_writer():
        return g.dump(tmp_path / "L1_X.json", {"k": 1})

    a_named_writer()
    got = json.loads((tmp_path / "L1_X.json").read_text())
    assert got[g.STAMP_KEY]["emitter"].endswith(".a_named_writer")
    assert "test_l_doc_generator_stamp" in got[g.STAMP_KEY]["emitter"]
