#!/usr/bin/env python3
"""`ppa_metric_extract.py` — the assembler's four fixtures, as real process
exit codes.

The assembler is the artefact every later PPA claim is built on, so the thing
that matters most about it is what it does when it CANNOT do its job: it must
not write a well-formed empty bundle, because a well-formed empty bundle is
indistinguishable from a clean run to everything downstream.

    positive   valid records in -> one bundle out, rc 0
    negative   a conflict, or an invalid record -> rc 1 AND NO BUNDLE WRITTEN
    vacuous    nothing to read, or nothing readable -> rc 2 with a marker
    mutation   test_ppa_metrics_mutation.py
"""
import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from _ppa import canonical_json as cj  # noqa: E402
from _ppa import metrics as M  # noqa: E402

PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
EXTRACT = PROGRAMS / "ppa_metric_extract.py"

SCOPE_SYNTH = {"stage": "synthesis"}
SCOPE_ROUTE = {"stage": "post_route_extracted", "process": "ss"}
SRC = {"path": "sta.rpt", "tool": "opensta"}


def run(*args):
    return subprocess.run([sys.executable, str(EXTRACT), *args],
                          capture_output=True, text=True)


def put(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")
    return str(path)


AREA = M.measured("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH, SRC)
POWER = M.measured("power.total_mw", 3.0, "mW", SCOPE_ROUTE, SRC)


# ------------------------------------------------------------- 1. POSITIVE

def test_positive_two_documents_become_one_bundle(tmp_path):
    d = tmp_path / "records"
    d.mkdir()
    put(d / "area.json", AREA)
    put(d / "power.json", [POWER])
    out = tmp_path / "bundle.json"
    p = run("--records", str(d), "--out", str(out))
    assert p.returncode == 0, p.stderr
    doc = json.loads(out.read_text())
    assert doc["schema"] == M.BUNDLE_SCHEMA_ID
    assert len(doc["records"]) == 2
    assert doc["records_digest"].startswith("sha256:")


def test_the_bundle_is_written_with_the_one_serializer(tmp_path):
    """Never a hand-rolled json.dumps for anything hashed: the digest inside
    the document must be reproducible by an independent reader who hashes the
    same object."""
    d = tmp_path / "records"
    d.mkdir()
    put(d / "area.json", AREA)
    out = tmp_path / "bundle.json"
    assert run("--records", str(d), "--out", str(out)).returncode == 0
    text = out.read_text(encoding="utf-8")
    doc = json.loads(text)
    assert text == cj.dumps(doc) + "\n"
    idx = M.MetricIndex()
    idx.extend(doc["records"])
    assert idx.digest() == doc["records_digest"]


def test_the_bundle_digest_does_not_depend_on_file_read_order(tmp_path):
    def build(names):
        d = tmp_path / ("r_" + "_".join(names))
        d.mkdir()
        for i, n in enumerate(names):
            put(d / f"{i}.json", AREA if n == "a" else POWER)
        out = d / "bundle.json"
        assert run("--records", str(d), "--out", str(out)).returncode == 0
        return json.loads(out.read_text())["records_digest"]
    assert build(["a", "p"]) == build(["p", "a"])


def test_the_denominator_travels_with_the_records(tmp_path):
    d = tmp_path / "records"
    d.mkdir()
    put(d / "area.json", AREA)
    expect = put(tmp_path / "expect.json",
                 {"expected": [{"metric": "area.die_um2",
                                "scope": SCOPE_SYNTH}]})
    out = tmp_path / "bundle.json"
    assert run("--records", str(d), "--expect", expect,
               "--out", str(out)).returncode == 0
    assert json.loads(out.read_text())["expected"]


# ------------------------------------------------------------- 2. NEGATIVE

def test_negative_two_records_claiming_one_fact_are_refused(tmp_path):
    d = tmp_path / "records"
    d.mkdir()
    put(d / "a.json", AREA)
    other = dict(AREA)
    other["value"] = 15400.0
    put(d / "b.json", other)
    p = run("--records", str(d))
    assert p.returncode == 1, (p.returncode, p.stdout, p.stderr)
    assert "CONFLICTING_RECORD" in p.stderr


def test_negative_a_refused_set_leaves_NO_bundle_behind(tmp_path):
    """An artefact left behind after a refusal is picked up by the next step as
    if it were one."""
    d = tmp_path / "records"
    d.mkdir()
    put(d / "a.json", AREA)
    other = dict(AREA)
    other["value"] = 15400.0
    put(d / "b.json", other)
    out = tmp_path / "bundle.json"
    p = run("--records", str(d), "--out", str(out))
    assert p.returncode == 1
    assert not out.exists(), "a refused record set wrote a bundle anyway"
    assert "[REFUSE]" in p.stderr


def test_negative_a_record_carrying_a_sentinel_is_refused(tmp_path):
    d = tmp_path / "records"
    d.mkdir()
    bad = M.not_measured("power.total_mw", "no VCD", SCOPE_ROUTE)
    bad["value"] = 0
    put(d / "bad.json", bad)
    p = run("--records", str(d))
    assert p.returncode == 1
    assert "VALUE_ON_A_NON_MEASUREMENT" in p.stderr


def test_negative_the_same_metric_at_two_scopes_is_NOT_a_conflict(tmp_path):
    """The mirror of the conflict test, and the reason the index is keyed on
    scope: two genuinely different facts must both survive."""
    d = tmp_path / "records"
    d.mkdir()
    put(d / "a.json", AREA)
    put(d / "b.json", M.measured("area.die_um2", 15400.0, "um^2",
                                 SCOPE_ROUTE, SRC))
    out = tmp_path / "bundle.json"
    p = run("--records", str(d), "--out", str(out))
    assert p.returncode == 0, p.stderr
    assert len(json.loads(out.read_text())["records"]) == 2


# -------------------------------------------------------------- 3. VACUOUS

def test_vacuous_an_empty_directory_exits_two_not_zero(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    p = run("--records", str(d))
    assert p.returncode == 2, (p.returncode, p.stdout, p.stderr)
    assert "[CANNOT CHECK]" in p.stderr


def test_vacuous_an_empty_directory_writes_no_bundle_that_reads_as_clean(tmp_path):
    """What the name says. Until v1.11.33 the body admitted the opposite: a
    bundle WAS written, `{"records": []}`, byte-identical to a run that read a
    tree and found nothing. The exit code was honest and the file was not, and
    a downstream reader opens the file."""
    d = tmp_path / "empty"
    d.mkdir()
    out = tmp_path / "bundle.json"
    p = run("--records", str(d), "--out", str(out))
    assert p.returncode == 2
    assert "no document was named or found" in p.stderr
    assert not out.exists(), out.read_text()


def test_vacuous_every_input_unreadable_writes_no_bundle(tmp_path):
    """Rule 9 at the artefact level. Nothing was read, so there is no record
    set -- empty or otherwise -- to write down."""
    d = tmp_path / "records"
    d.mkdir()
    (d / "broken.json").write_text("{not json", encoding="utf-8")
    (d / "other.json").write_text('{"schema": "something.else.v1"}',
                                  encoding="utf-8")
    out = tmp_path / "bundle.json"
    p = run("--records", str(d), "--out", str(out))
    assert p.returncode == 2
    assert not out.exists(), out.read_text()
    assert "not one document was read" in p.stderr


def test_a_partial_read_writes_a_bundle_that_SAYS_it_is_partial(tmp_path):
    """The honest-partial case still produces a bundle -- and the bundle names
    what it could not read, so a reader who opens the file and not the exit
    code can still see it."""
    d = tmp_path / "records"
    d.mkdir()
    put(d / "area.json", AREA)
    (d / "broken.json").write_text("{not json", encoding="utf-8")
    out = tmp_path / "bundle.json"
    p = run("--records", str(d), "--out", str(out))
    assert p.returncode == 2
    doc = json.loads(out.read_text())
    assert len(doc["records"]) == 1
    assert [u["path"] for u in doc["inputs_unreadable"]] == [str(d / "broken.json")]


def test_vacuous_a_named_file_that_is_missing_exits_two(tmp_path):
    p = run("--records", str(tmp_path / "nope.json"))
    assert p.returncode == 2
    assert "[CANNOT CHECK]" in p.stderr
    assert "MISSING" in p.stderr


def test_vacuous_an_unparseable_document_exits_two(tmp_path):
    d = tmp_path / "records"
    d.mkdir()
    (d / "broken.json").write_text("{not json", encoding="utf-8")
    p = run("--records", str(d))
    assert p.returncode == 2
    assert "BAD_JSON" in p.stderr


def test_vacuous_a_document_of_an_unknown_schema_exits_two_not_empty(tmp_path):
    """Rule 9 at the document level: an unrecognised document must not be read
    as a bundle of zero records."""
    d = tmp_path / "records"
    d.mkdir()
    put(d / "other.json", {"schema": "something.else.v1", "records": []})
    p = run("--records", str(d))
    assert p.returncode == 2
    assert "UNRECOGNISED_DOCUMENT" in p.stderr


def test_vacuous_a_backend_that_does_not_exist_refuses(tmp_path):
    """THE SEAM. A tool nobody has written a backend for must not produce a
    well-formed empty bundle that reads as 'nothing was found'."""
    p = run("--backend", "no_such_tool")
    assert p.returncode == 2
    assert "[CANNOT CHECK]" in p.stderr
    assert "nothing looked" in p.stderr


def test_no_arguments_is_a_bad_invocation_not_a_pass():
    p = run()
    assert p.returncode != 0
    assert p.returncode != 1
    # PPA_INTERFACES §1: 3 is BAD INVOCATION, 2 is "I could not check". A typo
    # and an unreadable input must not leave a caller the same exit code.
    assert p.returncode == 3, (p.returncode, p.stderr)


def test_the_report_names_its_denominator(tmp_path):
    """A count is stated over a named population or it is not stated."""
    d = tmp_path / "records"
    d.mkdir()
    put(d / "area.json", AREA)
    out = tmp_path / "report.json"
    p = run("--records", str(d), "--json", str(out))
    assert p.returncode == 0
    assert "document(s) named" in p.stdout
    report = json.loads(out.read_text())
    assert report["records"] == 1
    assert len(report["documents"]) == 1


def test_every_extract_verdict_carries_a_machine_readable_code(tmp_path):
    """PPA_INTERFACES §1. Two rc=2s -- 'no documents at all' and 'a document I
    could not read' -- are different problems with different fixes."""
    d = tmp_path / "records"
    d.mkdir()
    out = tmp_path / "r.json"
    assert run("--records", str(d), "--json", str(out)).returncode == 2
    assert json.loads(out.read_text())["code"] == "NOTHING_TO_READ"

    (d / "broken.json").write_text("{not json", encoding="utf-8")
    assert run("--records", str(d), "--json", str(out)).returncode == 2
    assert json.loads(out.read_text())["code"] == "INPUT_UNREADABLE"

    (d / "broken.json").unlink()
    put(d / "area.json", AREA)
    assert run("--records", str(d), "--json", str(out)).returncode == 0
    assert json.loads(out.read_text())["code"] == "BUNDLE_WRITTEN"

    other = dict(AREA)
    other["value"] = 15400.0
    put(d / "b.json", other)
    assert run("--records", str(d), "--json", str(out)).returncode == 1
    assert json.loads(out.read_text())["code"] == "RECORD_REFUSED"


# ── F-2: `--backend` drove no backend, including the ones that exist ────────
# Until v1.11.33 every `--backend TOOL` exited 2 with "ppa_metric_extract does
# not drive backends yet", for all five backends that ship. The canonical
# extraction CLI could extract from no tool at all, so a downloaded plugin had
# no supported route from a tool artefact to a record.

OPENROAD_LOG = """\
OpenROAD 26Q3-984-g09d67f08f8
[INFO IFP-0100] Die BBox:  (  0.000  0.000 ) ( 142.000 142.000 ) um
[INFO IFP-0102] Core area:                        12294.374 um^2
[INFO IFP-0105] Number of instances:                    252
[INFO DRT-0194] Start detail routing.
[INFO DRT-0199]   Number of violations = 0.
[INFO DRT-0198] Complete detail routing.
Total wire length = 12704 um.
Total number of vias = 2502.
"""


def test_the_backend_seam_actually_EXTRACTS(tmp_path):
    """THE F-2 GUARD, end to end through the process. Not "a backend declares a
    driver" -- that can be true while the CLI still extracts nothing -- but
    "records came out of a real artefact and into a bundle"."""
    log = tmp_path / "openroad.log"
    log.write_text(OPENROAD_LOG, encoding="utf-8")
    out = tmp_path / "bundle.json"
    p = run("--backend", "openroad", "--from", str(log), "--out", str(out))
    assert p.returncode == 0, p.stdout + p.stderr
    doc = json.loads(out.read_text())
    assert len(doc["records"]) > 0, "the backend was driven and indexed nothing"
    assert all(r["schema"] == M.SCHEMA_ID for r in doc["records"])
    assert any(r["metric"] == "route.wirelength.um" and r.get("value") == 12704.0
               for r in doc["records"]), "the figure the log states is missing"


def test_a_backend_that_cannot_be_driven_gives_its_OWN_reason(tmp_path):
    """A blanket refusal for every tool is what hid F-2 for eleven versions.
    A backend that is not a record producer must say so in its own words, and
    name what IS drivable."""
    art = tmp_path / "sta.rpt"
    art.write_text("worst slack max 5.24\n", encoding="utf-8")
    p = run("--backend", "opensta", "--from", str(art))
    assert p.returncode == 2, p.stdout + p.stderr
    assert "[CANNOT CHECK]" in p.stderr
    assert "not into records" in p.stderr, p.stderr
    assert "openroad" in p.stderr, "the refusal names no drivable alternative"


def test_vacuous_a_backend_with_no_artefact_refuses_and_writes_nothing(tmp_path):
    """--from naming nothing is not an empty extraction."""
    out = tmp_path / "bundle.json"
    p = run("--backend", "openroad", "--from", str(tmp_path / "nope.log"),
            "--out", str(out))
    assert p.returncode == 2
    assert not out.exists()
    assert "no such artefact" in p.stderr


def test_a_backend_that_needs_an_option_refuses_rather_than_defaulting(tmp_path):
    """yosys prints two statistics blocks in one transcript and they are two
    stages of one run. Defaulting the stage compares a pre-techmap count
    against a mapped one and nothing downstream can see it happened."""
    art = tmp_path / "stat.txt"
    art.write_text("=== design hierarchy ===\n   cells 252\n", encoding="utf-8")
    p = run("--backend", "yosys", "--from", str(art))
    assert p.returncode == 3, (p.returncode, p.stdout, p.stderr)
    assert "--stage" in p.stderr
