"""#2057 item 1 — the Phase-1 round trip keeps every layer the renderer writes.

THE DEFECT, measured on v1.17.89+cz2050 before this change
(`from_existing_docs` walked `ALL_LAYER_CODES`, 14 codes, while
`render_layers` could write `GENERATABLE_LAYER_CODES`, 28):

    fixture          files on disk   layers ingested   re-rendered
    accept_a2b            24              14               14
    accept_espi           24              14               14
    accept_lpddr5         24              14               14
    dropped, all three: L14 L15 L16 L17 L18 L19 L20 L21 L22 L23

cz2050 pinned that shortfall by name rather than asserting a green that was
not there. These tests are the green, and they are written so the shortfall
CANNOT come back quietly:

  * the ingest population is the RENDERER's own list, not a second hand-fed
    register beside it — `_ROUND_TRIP_LAYER_CODES is GENERATABLE_LAYER_CODES`,
    checked by identity, and no layer-code list literal is allowed to
    reappear in ingest.py (parsed with `ast`, not grepped);
  * the three 24-layer fixtures must come back with the SAME FILE-NAME SET
    they went in with — membership, never a count;
  * the 14-layer control must round-trip unchanged, so a mutation that
    reddens the advanced layers leaves it green.

A SECOND CAUSE, found while measuring the first and fixed with it: walking
28 codes reached only 20 of the 24 layers, because `LAYER_FILE_NAMES` mapped
L16 / L18 / L20 / L23 to short names (`L16_COMPLIANCE.json`, …) that no
producer in this repo writes. `programs/l_doc_taxonomy.py` is the naming
authority; the last test here holds the two maps together so they cannot
diverge again.
"""
import ast
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve()
_PLUGIN = _HERE.parents[2]
_REPO = _PLUGIN.parents[2]
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_PLUGIN / "programs"))

from tools.phase1_engine import ingest as _ingest          # noqa: E402
from tools.phase1_engine import render as _render          # noqa: E402
from tools.phase1_engine.schema import (                   # noqa: E402
    ALL_LAYER_CODES, ADVANCED_LAYER_CODES, GENERATABLE_LAYER_CODES,
    LAYER_FILE_NAMES)

_FIXTURES = (_PLUGIN / "programs" / "tests" / "fixtures"
             / "stage_phase1_on_pass_review")
#: The three doc sets #2050 reproduced the drop on. Named, so this is a
#: population a reader can check rather than a glob that can quietly shrink.
_TWENTY_FOUR_LAYER_FIXTURES = ("accept_a2b", "accept_espi", "accept_lpddr5")


def _docs(name):
    return _FIXTURES / name / "phase1" / "generated_docs"


def _round_trip(src: Path, out: Path):
    graph = _ingest.from_existing_docs(src)
    _render.render_layers(graph, out)
    return graph, sorted(p.name for p in out.glob("*.json"))


# ---------------------------------------------------------------------------
# ONE population, and it is the renderer's
# ---------------------------------------------------------------------------
def test_the_ingest_population_is_the_renderers_own_list_by_identity():
    """Not "equal to" — the SAME OBJECT. Two lists that happen to agree today
    are exactly what drifted: `ALL_LAYER_CODES` and `GENERATABLE_LAYER_CODES`
    agreed until L14 was added."""
    assert _ingest._ROUND_TRIP_LAYER_CODES is GENERATABLE_LAYER_CODES


def test_ingest_walks_no_hand_written_layer_code_list():
    """Parsed with `ast`, so a list reintroduced under any name is caught.

    A list/tuple literal whose elements are all `L<digits>`-shaped strings is
    a hand-fed layer register; there must be none in ingest.py.
    """
    tree = ast.parse(Path(_ingest.__file__).read_text())
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            continue
        vals = [e.value for e in node.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if len(vals) == len(node.elts) and len(vals) >= 3 and all(
                v.startswith("L") and v[1:].rstrip("RCT").isdigit()
                for v in vals):
            offenders.append(vals)
    assert offenders == [], (
        "ingest.py carries a hand-written layer-code list: "
        + "; ".join(" ".join(o) for o in offenders))


def test_ingest_reads_every_layer_the_renderer_can_write():
    """Behavioural, not source-read: one file per generatable code goes in,
    every code must come back as a fact view."""
    with tempfile.TemporaryDirectory() as t:
        src = Path(t)
        for code in GENERATABLE_LAYER_CODES:
            (src / LAYER_FILE_NAMES[code]).write_text(
                '{"probe_%s": "v"}' % code.lower())
        graph = _ingest.from_existing_docs(src)
    seen = {v for f in graph.facts for v in f.views}
    missing = sorted(set(GENERATABLE_LAYER_CODES) - seen)
    assert seen == set(GENERATABLE_LAYER_CODES), (
        f"the reverse extract dropped {len(missing)} of "
        f"{len(GENERATABLE_LAYER_CODES)} layers: {' '.join(missing)}")


def test_structured_yaml_reads_the_same_population():
    """`from_structured_yaml` is the other door onto the same fact graph and
    walked the same 14-code list. Both doors, one population."""
    import yaml
    doc = {"ic_name": "RT", "class_path": "probe"}
    for code in GENERATABLE_LAYER_CODES:
        doc[code] = {"probe": code}
    with tempfile.TemporaryDirectory() as t:
        p = Path(t) / "s.yaml"
        p.write_text(yaml.safe_dump(doc))
        graph = _ingest.from_structured_yaml(p)
    seen = {v for f in graph.facts for v in f.views}
    missing = sorted(set(GENERATABLE_LAYER_CODES) - seen)
    assert seen == set(GENERATABLE_LAYER_CODES), (
        f"from_structured_yaml dropped {len(missing)} of "
        f"{len(GENERATABLE_LAYER_CODES)} layers: {' '.join(missing)}")


# ---------------------------------------------------------------------------
# The three fixtures the drop was reproduced on
# ---------------------------------------------------------------------------
def test_the_three_24_layer_fixtures_round_trip_whole():
    """MEMBERSHIP, both ways: the file-name set out is the file-name set in.

    Before #2057 this was 14 of 24 on all three.
    """
    for name in _TWENTY_FOUR_LAYER_FIXTURES:
        src = _docs(name)
        went_in = sorted(p.name for p in src.glob("*.json"))
        assert len(went_in) == 24, f"{name}: fixture changed shape: {went_in}"
        with tempfile.TemporaryDirectory() as t:
            _, came_out = _round_trip(src, Path(t))
        dropped = sorted(set(went_in) - set(came_out))
        invented = sorted(set(came_out) - set(went_in))
        assert came_out == went_in, (
            f"{name}: dropped {len(dropped)} -> {' '.join(dropped)} | "
            f"invented {len(invented)} -> {' '.join(invented)}")


def test_the_cli_round_trip_command_itself_keeps_every_layer(tmp_path):
    """THE COMMAND THE ISSUE NAMES, end to end, as a subprocess.

    Every other test here calls `from_existing_docs` and `render_layers`
    directly. `phase1_engine.cli round-trip` also SERIALISES THROUGH
    `facts.yaml` in between — `FactGraph.save` then the render — and a fact's
    `views` list surviving that is a separate question from the reverse
    extract reading the file at all. Asserting the two halves and not the
    whole is how a round trip passes in pieces and drops layers in practice.

    MEASURED both directions on the same three fixtures, same command:

        untouched v1.17.95 (d52e67bb9)   24 in -> 14 out, rc 0, ten dropped
        this branch                      24 in -> 24 out, rc 0, none dropped

    `rc 0` on BOTH sides is the point: the drop was silent, so no exit code
    ever carried it.
    """
    repo = _PLUGIN.parents[2]
    for name in _TWENTY_FOUR_LAYER_FIXTURES:
        src = _docs(name)
        out = tmp_path / name
        r = subprocess.run(
            [sys.executable, "-m", "tools.phase1_engine.cli", "round-trip",
             str(src), "--out-dir", str(out)],
            cwd=str(repo), capture_output=True, text=True)
        assert r.returncode == 0, (name, r.stderr[-500:])
        assert (out / "facts.yaml").is_file(), name
        went_in = sorted(p.name for p in src.glob("*.json"))
        came_out = sorted(p.name for p in (out / "generated_docs").glob("*.json"))
        dropped = sorted(set(went_in) - set(came_out))
        invented = sorted(set(came_out) - set(went_in))
        assert came_out == went_in, (
            f"{name}: the CLI round trip dropped {len(dropped)} -> "
            f"{' '.join(dropped)} | invented {' '.join(invented)}")


def test_a_fourteen_layer_doc_set_round_trips_unchanged():
    """THE CONTROL. A doc set holding only the REQUIRED layers must be
    unaffected by everything above — so a mutation that reddens the advanced
    layers leaves this green, and a change that reddens this one is a
    regression in the ordinary path, not in the opt-in one."""
    required = {LAYER_FILE_NAMES[c] for c in ALL_LAYER_CODES}
    with tempfile.TemporaryDirectory() as t:
        src = Path(t) / "in"
        src.mkdir()
        for p in sorted(_docs("accept_a2b").glob("*.json")):
            if p.name in required:
                (src / p.name).write_bytes(p.read_bytes())
        went_in = sorted(p.name for p in src.glob("*.json"))
        assert went_in == sorted(required)
        _, came_out = _round_trip(src, Path(t) / "out")
    assert came_out == went_in


def test_the_advanced_layers_are_still_opt_in_not_required():
    """The round trip carrying L14..L27 must NOT make them mandatory — the
    'all L docs present' gates key on ALL_LAYER_CODES and a simple digital
    block still owes 14 documents, not 28. This is the half of cz2050's
    pinned list that is a real invariant rather than a shortfall."""
    assert [c for c in GENERATABLE_LAYER_CODES if c not in ALL_LAYER_CODES] \
        == list(ADVANCED_LAYER_CODES)
    assert len(ALL_LAYER_CODES) == 14 and len(GENERATABLE_LAYER_CODES) == 28


# ---------------------------------------------------------------------------
# The filename map, held against the naming authority
# ---------------------------------------------------------------------------
def test_the_engine_filename_map_agrees_with_the_l_doc_taxonomy():
    """`programs/l_doc_taxonomy.py` is the authority for an L-document's file
    name. L16 / L18 / L20 / L23 disagreed with it, in the direction of names
    that appear in ZERO produced doc set — the same shape the L11 comment in
    schema.py already records. Held together here so the next one is caught
    by a test instead of by a dropped layer."""
    import dataclasses
    import l_doc_taxonomy as tax
    declared = {}
    for group in (tax.L_DOCS_V1, tax.L_DOCS_V2, tax.L_DOCS_V2_PROTOCOL_EXT,
                  tax.L_DOCS_V2_FLOW_EXT, tax.L_DOCS_V2_COMPLETENESS_EXT):
        for spec in group:
            declared[spec.code] = dataclasses.astuple(spec)[1] + ".json"
    # L8 / L8R are the engine's spelling of the taxonomy's L8T / L8C; compare
    # by FILE NAME, which is the thing both sides actually open.
    mismatch = {c: (LAYER_FILE_NAMES[c], declared[c])
                for c in LAYER_FILE_NAMES
                if c in declared and LAYER_FILE_NAMES[c] != declared[c]}
    assert mismatch == {}, (
        "engine map disagrees with l_doc_taxonomy: "
        + "; ".join(f"{c}: engine {e} vs taxonomy {t}"
                    for c, (e, t) in sorted(mismatch.items())))
    assert set(LAYER_FILE_NAMES.values()) >= set(declared.values()), (
        sorted(set(declared.values()) - set(LAYER_FILE_NAMES.values())))


def test_the_master_engine_and_the_bundled_engine_carry_the_same_maps():
    """The master is `<repo>/tools/phase1_engine`; the plugin payload bundles a
    byte-identical twin. Fixing only the bundle is how the L11 name regressed
    once already (schema.py says so in its own comment), so the three files
    this change touches are compared here by bytes."""
    master = _REPO / "tools" / "phase1_engine"
    bundled = _PLUGIN / "tools" / "phase1_engine"
    if not (master / "schema.py").is_file():        # installed cache: no master
        return
    for name in ("schema.py", "ingest.py", "render.py"):
        assert (master / name).read_bytes() == (bundled / name).read_bytes(), \
            f"{name}: master and bundled engine differ"


# ---------------------------------------------------------------------------
# The OTHER half of X_round_trip_byte_identical, pinned by name, NOT fixed
# ---------------------------------------------------------------------------
def test_the_round_trip_is_not_yet_byte_identical_and_says_exactly_why():
    """#2057's brief asks for a control that "a 14-layer doc set round-trips
    BYTE-IDENTICAL". It does not, and it did not before this change either —
    measured 0 of 14 on the untouched v1.17.95 and 0 of 14 here, with the same
    causes. cz2050's dead `X_round_trip_byte_identical` key had TWO halves;
    #2057 fixed the LAYER population, and this is the residual.

    Pinned by NAME rather than asserted green, exactly as cz2050 pinned the
    layer drop, so it is a list the next lane can shrink instead of a claim in
    a document. It reddens BOTH ways: if a key stops being lost, or a new one
    starts being lost, this fails and says which.

    TWO DIFFERENT CAUSES, and only one of them is a defect:

      ADDED, BY DESIGN — `render_layers` injects `source_documents` and
      `provenance` (the D6 traceability rubric) and stamps `_generator` at the
      L-document write chokepoint. A re-render is therefore MORE traceable
      than its input, never less. Not a loss.

      LOST, A REAL DEFECT — every lost key holds an EMPTY DICT. `_walk_leaves`
      emits no leaf for an empty container, so "this section exists and is
      empty" is not representable in the fact graph and vanishes on re-render.
      An empty section is a STATEMENT — it is how a document says a question
      was asked and answered "none" — and it is being silently dropped. Same
      shape as the layer drop this issue fixed, one level down.

    NOT FIXED HERE: `_walk_leaves` is the ingest chokepoint for every input
    door, and changing what it emits for an empty container moves every
    downstream L-doc consumer. That belongs in its own lane with its own
    corpus sweep, not bundled into a three-item fix.
    """
    import json
    required = {LAYER_FILE_NAMES[c] for c in ALL_LAYER_CODES}
    src_dir = _docs("accept_a2b")
    with tempfile.TemporaryDirectory() as t:
        src = Path(t) / "in"
        src.mkdir()
        for p in sorted(src_dir.glob("*.json")):
            if p.name in required:
                (src / p.name).write_bytes(p.read_bytes())
        out = Path(t) / "out"
        _round_trip(src, out)

        identical, lost, added, non_empty_losses = 0, set(), set(), {}
        for p in sorted(src.glob("*.json")):
            q = out / p.name
            if q.read_bytes() == p.read_bytes():
                identical += 1
                continue
            a, b = json.loads(p.read_text()), json.loads(q.read_text())
            for k in set(a) - set(b):
                lost.add(k)
                if a[k] not in ({}, [], None, ""):
                    non_empty_losses[f"{p.name}:{k}"] = type(a[k]).__name__
            added |= set(b) - set(a)

    assert identical == 0, (
        f"{identical} of 14 are now byte-identical — the round trip got "
        "better and this pin must be shrunk to say so")
    assert added == {"_generator", "provenance", "source_documents"}, (
        f"keys the re-render adds changed: {' '.join(sorted(added))}")
    assert sorted(lost) == ["extraction_evidence", "otp_ip_macro",
                            "rig_pin_assignments"], (
        f"the set of LOST keys moved: {' '.join(sorted(lost))}")
    # THE LOAD-BEARING HALF: every loss must be an EMPTY container. A loss of
    # anything with content is a different, worse defect and must not hide
    # behind this pin.
    assert non_empty_losses == {}, (
        "a key with CONTENT was lost, which this pin does not cover: "
        + "; ".join(f"{k} ({v})" for k, v in sorted(non_empty_losses.items())))


def test_the_production_run_all_path_is_unchanged_for_an_ordinary_design(
        tmp_path):
    """THE BLAST RADIUS, on the entry point that actually ships.

    #2057 changes `render_layers`' default from ALL_LAYER_CODES to
    GENERATABLE_LAYER_CODES. Three call sites take that default, and one of
    them is `cli.py run-all` — which is what `phase1_one_shot_runner` drives
    for every prompt-mode Phase-1 run. A default change there is a change to
    what real designs emit, so it is measured here rather than reasoned about.

    MEASURED, base v1.17.95 vs this branch, same command:

        input                  BASE   BRANCH
        24-layer doc set        14      24     <- the drop, and the fix
        ordinary 14-layer set   14      14     <- UNCHANGED

    The second row is the one that matters for blast radius: an ordinary
    design emits exactly what it always did. Extra layers appear only when the
    INPUT carries them, because `render_layers` skips a layer with no facts
    and the NL door does not tag facts outside ALL_LAYER_CODES.
    """
    required = {LAYER_FILE_NAMES[c] for c in ALL_LAYER_CODES}
    repo = _PLUGIN.parents[2]
    src24 = _docs("accept_a2b")

    src14 = tmp_path / "in14"
    src14.mkdir()
    for p in sorted(src24.glob("*.json")):
        if p.name in required:
            (src14 / p.name).write_bytes(p.read_bytes())

    def run_all(src, out):
        r = subprocess.run(
            [sys.executable, "-m", "tools.phase1_engine.cli", "run-all",
             str(src), str(out), "--allow-underspec"],
            cwd=str(repo), capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-400:]
        return sorted(p.name for p in (out / "generated_docs").glob("*.json"))

    ordinary = run_all(src14, tmp_path / "out14")
    assert len(ordinary) == 14, (
        "an ORDINARY design's Phase-1 output changed shape: "
        f"{len(ordinary)} L-docs -> {' '.join(ordinary)}")
    assert sorted(ordinary) == sorted(required)

    advanced = run_all(src24, tmp_path / "out24")
    assert len(advanced) == 24, (
        f"the advanced doc set emitted {len(advanced)} of 24: "
        f"{' '.join(advanced)}")


def test_the_human_docs_cover_the_same_layers_as_the_json(tmp_path):
    """THE MARKDOWN HALF, which no test of mine reached until now.

    #2057 changes TWO defaults in render.py — `render_layers` AND
    `render_markdown_layers`. Every other test here exercises only the JSON
    side, so the second change was shipping unverified on a production path:
    `cli.py run-all` calls `render_human_docs(graph, human_out)` with no
    `layers` argument (cli.py:532).

    It matters because the asymmetry is the defect. Without the markdown
    default moving too, an advanced design gets 24 machine-readable layer
    documents and only 14 human-readable ones, and the human set — the one a
    reviewer actually reads — silently omits exactly the layers this issue
    exists to stop dropping.

    MEASURED via run-all on the 24-layer fixture:  BASE json=14 md=15,
    BRANCH json=24 md=25. The +1 is `PROVENANCE.md`, which is not an L
    document; this test therefore compares LAYER SETS, never raw file counts.
    """
    repo = _PLUGIN.parents[2]
    out = tmp_path / "out"
    r = subprocess.run(
        [sys.executable, "-m", "tools.phase1_engine.cli", "run-all",
         str(_docs("accept_a2b")), str(out), "--allow-underspec"],
        cwd=str(repo), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-400:]

    json_stems = {p.stem for p in (out / "generated_docs").glob("*.json")}
    md_stems = {p.stem for p in out.rglob("*.md")
                if p.stem.startswith("L") and p.stem[1:2].isdigit()}
    assert json_stems, "run-all emitted no L-document JSON at all"
    missing = sorted(json_stems - md_stems)
    extra = sorted(md_stems - json_stems)
    assert missing == [] and extra == [], (
        f"the human docs do not cover the same layers as the JSON — "
        f"{len(json_stems)} json vs {len(md_stems)} md; "
        f"no human doc for: {' '.join(missing) or 'none'}; "
        f"human doc with no json: {' '.join(extra) or 'none'}")
    assert len(json_stems) == 24, (
        f"fixture shape changed: {len(json_stems)} layers")
    # PROVENANCE.md is not an L document and is deliberately outside the
    # comparison; assert it is really there so the filter is not silently
    # excluding something else.
    assert (out / "PROVENANCE.md").is_file() or any(
        p.name == "PROVENANCE.md" for p in out.rglob("*.md"))
