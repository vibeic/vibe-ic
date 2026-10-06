"""W0's import manifest carries several runs (llv1 W6 on W0).

The ``--librelane`` plan runs LibreLane twice and imports both runs at once.
``_external_flow_manifest`` writes one run flat (``run_dir`` + ``rows``, the
form every one-run reader already reads) and two or more as ``segments``;
readers go through ``segments_of``. These tests build the manifests with the
real importer on the CMP3 fixtures (``fixtures/librelane_import``), then
check what W0's writer, validator and readers accept and refuse.
"""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
_PLUGIN = PROGRAMS.parent
for _p in (str(PROGRAMS), str(_PLUGIN)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

FIXTURE = (Path(__file__).resolve().parent / "fixtures" / "librelane_import"
           / "8HD-4" / "runs" / "cmp3")
CHECK = PROGRAMS / "provenance_check.py"
ONE = "phase3/librelane/runs/cmp3"
SEG1, SEG2 = "phase3/librelane/seg1/runs/cmp3", "phase3/librelane/seg2/runs/cmp3"
SEG1_END = "Checker.NetlistAssignStatements"


def _running(lines, needle):
    return next(i for i, l in enumerate(lines)
                if l.startswith("Running") and needle in l)


def _one_run(tmp_path: Path) -> Path:
    import librelane_import as LI
    proj = tmp_path / "proj"
    (proj / ONE).parent.mkdir(parents=True)
    shutil.copytree(FIXTURE, proj / ONE)
    LI.import_run(proj, proj / ONE)
    return proj


def _two_runs(tmp_path: Path) -> Path:
    """Segment 1 --to NetlistAssignStatements, segment 2 from CheckSDCFiles,
    each flow.log the real one cut the way LibreLane writes such a run.
    Segment 1 keeps only the folders it ran, so a row read against the wrong
    segment's run_dir finds nothing."""
    import librelane_import as LI
    proj = tmp_path / "proj"
    for rel in (SEG1, SEG2):
        (proj / rel).parent.mkdir(parents=True)
        shutil.copytree(FIXTURE, proj / rel)
    lines = (proj / SEG1 / "flow.log").read_text().splitlines(keepends=True)
    cut = _running(lines, "'OpenROAD.CheckSDCFiles'")
    end = [l for l in lines if l.startswith(("Saving views", "Flow complete."))]

    def skipped(part):
        # LibreLane's --to/--from loop prints a skip for every top-level step
        # outside the selected range. Keep those lines so the segment joint
        # can be checked while the manifest assertions below stay identical.
        return [f"Skipping step '{l.split(chr(39))[1]}'…\n" for l in part
                if l.startswith("Running '") and "/" not in
                l.split(" at ")[1].strip("'…\n").split("runs/cmp3/", 1)[1]]

    (proj / SEG1 / "flow.log").write_text(
        "".join(lines[:cut] + skipped(lines[cut:]) + end))
    (proj / SEG2 / "flow.log").write_text(
        "Starting…\n" + "".join(skipped(lines[1:cut]) + lines[cut:]))
    # the trim kept state_out.json only where a rule imports; LibreLane
    # writes one for every step that returns, the declared end included
    (proj / SEG1 / "09-checker-netlistassignstatements/state_out.json") \
        .write_text("{}\n")
    for d in (proj / SEG1).iterdir():
        if d.is_dir() and d.name[:2].isdigit() and int(d.name[:2]) > 9:
            shutil.rmtree(d)
    LI.import_segments(proj, [(proj / SEG1, SEG1_END), (proj / SEG2, None)])
    return proj


def _manifest(proj: Path):
    import _external_flow_manifest as M
    return json.loads(M.manifest_path(proj).read_text())


# ── the one-run form is exactly W0's flat form ────────────────────────────

def test_one_run_is_written_flat_and_reads_as_before(tmp_path):
    import _external_flow_manifest as M
    proj = _one_run(tmp_path)
    doc = M.load_manifest(proj)                    # validated against disk
    assert "segments" not in doc
    assert doc["schema"] == M.SCHEMA and doc["run_dir"] == ONE
    # This is a native Classic run, not a run_chain receipt fixture. Its
    # mapped headers prove transport only; import cannot invent extraction.
    assert not list((proj / ONE).rglob("vibeic_receipt.json"))
    spefs = [r for r in doc["rows"] if r["canonical_path"].endswith(".spef")]
    assert spefs
    for row in spefs:
        assert row["measurement"]["measured"] is False, row
        source = proj / ONE / row["tool_run_path"]
        copied = proj / row["canonical_path"]
        assert source.read_bytes() == copied.read_bytes()
        assert row["canonical_sha256"] == row["tool_run_sha256"]
    assert doc["flow_status"]["complete"] is True
    assert len(doc["rows"]) > 100
    for row in doc["rows"]:
        assert not [k for k in M.ROW_KEYS if k not in row], row
        assert "run_dir" not in row                # the run is the manifest's
    segs = M.segments_of(doc)
    assert segs == [{"name": None, "run_dir": ONE, "rows": doc["rows"],
                     "flow_status": doc["flow_status"]}]


# ── two runs: segments ─────────────────────────────────────────────────────

def test_two_runs_are_segments_each_read_against_its_own_run(tmp_path):
    import _external_flow_manifest as M
    proj = _two_runs(tmp_path)
    doc = M.load_manifest(proj)
    assert not {"run_dir", "rows", "flow_status"} & set(doc)
    segs = M.segments_of(doc)
    assert [(s["name"], s["run_dir"]) for s in segs] == \
        [("segment-1", SEG1), ("segment-2", SEG2)]
    by = {r["canonical_path"]: s["run_dir"] for s in segs for r in s["rows"]}
    assert by["phase2/stage2/synth/netlist.v"] == SEG1
    assert by["phase3/stage3/pnr/routed.def"] == SEG2
    assert [s["flow_status"]["to"] for s in segs] == [SEG1_END, None]


def test_w0s_provenance_reader_accepts_every_row_of_every_segment(tmp_path):
    """`to_provenance_entry` (W0's reader, built on W19's witnessed_row)
    accepts each row against its segment's run_dir, and provenance_check
    binds an output of each segment."""
    import _external_flow_manifest as M
    proj = _two_runs(tmp_path)
    n = 0
    for seg in M.segments_of(M.load_manifest(proj)):
        for row in seg["rows"]:
            if row["provenance"] != "witnessed":
                continue
            entry = M.to_provenance_entry(row, proj, seg["run_dir"])
            assert entry["witness"]["run_dir"] == seg["run_dir"]
            n += 1
    assert n > 100
    for out, tools in (("phase2/stage2/synth/netlist.v", "yosys"),
                       ("phase3/stage3/pnr/routed.def", "openroad")):
        r = subprocess.run([sys.executable, str(CHECK), str(proj), "--output",
                            out, "--tool", tools], capture_output=True,
                           text=True, timeout=120)
        assert r.returncode == 0, (out, r.stdout)


def _problems(proj, doc):
    import _external_flow_manifest as M
    return M.validate_manifest(doc, proj, verify_disk=True)


def test_a_row_read_against_the_other_segments_run_is_refused(tmp_path):
    proj = _two_runs(tmp_path)
    doc = _manifest(proj)
    assert _problems(proj, doc) == []
    swapped = copy.deepcopy(doc)
    a, b = swapped["segments"]
    a["run_dir"], b["run_dir"] = b["run_dir"], a["run_dir"]
    probs = _problems(proj, swapped)
    assert any(p.startswith("segment 'segment-1' row") for p in probs) or \
        any(p.startswith("segment 'segment-2' row") for p in probs), probs
    assert any("is not a file on disk" in p for p in probs), probs


@pytest.mark.parametrize("edit,why", [
    (lambda d: d.update(segments=d["segments"][:1]), "two or more runs"),
    (lambda d: d.update(run_dir=d["segments"][0]["run_dir"]),
     "per segment, not at the top"),
    (lambda d: d["segments"][1].update(name="segment-1"), "repeat a name"),
    (lambda d: d["segments"][1].update(run_dir=d["segments"][0]["run_dir"]),
     "repeat a run_dir"),
    (lambda d: d["segments"][1].pop("rows"), "is missing ['rows']"),
    (lambda d: d["segments"][0].update(name=""), "name is not a non-empty"),
    (lambda d: d["segments"][0].update(flow_status="done"),
     "flow_status, when present, is an object"),
])
def test_a_malformed_segment_list_is_refused(tmp_path, edit, why):
    proj = _two_runs(tmp_path)
    doc = _manifest(proj)
    edit(doc)
    probs = _problems(proj, doc)
    assert any(why in p for p in probs), probs


def test_a_file_imported_by_two_segments_is_refused(tmp_path):
    proj = _two_runs(tmp_path)
    doc = _manifest(proj)
    s1, s2 = doc["segments"]
    # a segment-1 row, also claimed by segment 2 (whose run holds the same
    # step folder, so the row itself is valid there)
    s2["rows"].append(copy.deepcopy(s1["rows"][0]))
    probs = _problems(proj, doc)
    assert any("is already imported by segment 'segment-1'" in p
               for p in probs), probs


def test_write_manifest_takes_one_form(tmp_path):
    import _external_flow_manifest as M
    proj = _two_runs(tmp_path)
    doc = _manifest(proj)
    segs = doc["segments"]
    with pytest.raises(M.ManifestError, match="not both"):
        M.write_manifest(proj, flow="librelane", run_dir=SEG1,
                         rows=segs[0]["rows"], segments=segs)
    with pytest.raises(M.ManifestError, match="not both and not neither"):
        M.write_manifest(proj, flow="librelane")
    with pytest.raises(M.ManifestError, match="per segment"):
        M.write_manifest(proj, flow="librelane", segments=segs,
                         flow_status={"complete": True})
    with pytest.raises(M.ManifestError, match="manifest's own keys"):
        M.write_manifest(proj, flow="librelane", segments=segs,
                         extra={"rows": []})
    before = M.manifest_path(proj).read_bytes()
    bad = copy.deepcopy(segs)
    bad[1]["rows"][0]["tool_run_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(M.ManifestError):
        M.write_manifest(proj, flow="librelane", segments=bad)
    assert M.manifest_path(proj).read_bytes() == before     # invalid → nothing


# ── W0 fix 3's measurement rule holds inside every segment ─────────────────

def _derived_row(doc, seg_index: int):
    """A row of that segment whose artefact yields a derived record."""
    return next(r for r in doc["segments"][seg_index]["rows"]
                if r["measurement"] is not None)


@pytest.mark.parametrize("seg_index", [0, 1])
@pytest.mark.parametrize("edit,why", [
    # a self-report: measured true, stated by the caller, not the artefact
    (lambda r: r.update(measurement=dict(r["measurement"], measured=True,
                                         stated_by="self")),
     "is not the record derived from the imported artefact"),
    # another tool's record
    (lambda r: r.update(measurement=dict(r["measurement"], tool="klayout")),
     "'s record, not"),
    # a record naming no tool
    (lambda r: r.update(measurement={k: v for k, v in r["measurement"].items()
                                     if k != "tool"}),
     "'s record, not"),
])
def test_a_measurement_not_derived_from_the_artefact_is_refused_in_a_segment(
        tmp_path, seg_index, edit, why):
    import _external_flow_manifest as M
    proj = _two_runs(tmp_path)
    doc = _manifest(proj)
    row = _derived_row(doc, seg_index)
    assert row["measurement"] == M.derived_measurement(
        proj, row["canonical_path"], row["tool"])          # as written
    edit(row)
    name = doc["segments"][seg_index]["name"]
    probs = _problems(proj, doc)
    assert any(p.startswith(f"segment {name!r} row") and why in p
               for p in probs), probs
    # and W0's writer refuses to write it
    with pytest.raises(M.ManifestError):
        M.write_manifest(proj, flow="librelane", segments=doc["segments"])


@pytest.mark.parametrize("seg_index", [0, 1])
def test_null_cannot_hide_a_derivable_measurement_in_a_segment(tmp_path,
                                                               seg_index):
    """W0 fix 4: a row's measurement EQUALS the derivation; null is valid
    only where the artefact yields none. Holds in every segment."""
    import _external_flow_manifest as M
    proj = _two_runs(tmp_path)
    doc = _manifest(proj)
    nulls = [r for s in doc["segments"] for r in s["rows"]
             if r["measurement"] is None]
    assert nulls and all(M.derived_measurement(proj, r["canonical_path"],
                                               r["tool"]) is None
                         for r in nulls)            # null where none derives
    row = _derived_row(doc, seg_index)
    row["measurement"] = None
    name = doc["segments"][seg_index]["name"]
    probs = _problems(proj, doc)
    assert any(p.startswith(f"segment {name!r} row") and "is null but" in p
               for p in probs), probs


# ── a manifest never records a run that did not finish (review W6 wave 6) ──

@pytest.mark.parametrize("edit,why", [
    (lambda d: d["flow_status"].update(complete=False),
     "flow_status.complete is not true"),
    (lambda d: d["flow_status"].pop("complete"),
     "flow_status.complete is not true"),
    (lambda d: d["not_performed"][0].update(flow_complete=False),
     "not_performed[0]: flow_complete is not true"),
    (lambda d: d["not_performed"].append("PadRing"),
     "is not an object"),
])
def test_a_one_run_manifest_of_an_unfinished_run_is_refused(tmp_path, edit, why):
    import _external_flow_manifest as M
    proj = _one_run(tmp_path)
    doc = _manifest(proj)
    assert _problems(proj, doc) == [] and doc["not_performed"]
    edit(doc)
    probs = _problems(proj, doc)
    assert any(why in p for p in probs), probs
    with pytest.raises(M.ManifestError):
        M.write_manifest(proj, flow="librelane", run_dir=doc["run_dir"],
                         rows=doc["rows"], flow_status=doc.get("flow_status"),
                         not_performed=doc["not_performed"])


@pytest.mark.parametrize("seg_index", [0, 1])
def test_a_segment_of_an_unfinished_run_is_refused(tmp_path, seg_index):
    proj = _two_runs(tmp_path)
    doc = _manifest(proj)
    doc["segments"][seg_index]["flow_status"]["complete"] = False
    name = doc["segments"][seg_index]["name"]
    probs = _problems(proj, doc)
    assert any(p.startswith(f"segment {name!r} flow_status.complete is not "
                            "true") for p in probs), probs
