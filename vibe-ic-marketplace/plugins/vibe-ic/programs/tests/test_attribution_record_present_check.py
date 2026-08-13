#!/usr/bin/env python3
"""Vendored third-party code may not lose its attribution record. vibe-ic#1043.

The obligation is Apache-2.0 §4(b)/§4(d), which attach to distributing the WORK
rather than to publishing a run that used it. So the interesting assertions are
the two DIRECTIONS: a licenced file with no record must FAIL, and a licenced file
with a record must PASS. Either alone is satisfiable by a constant.

The fixtures are synthetic git repositories owned by this file, so the tests do
not depend on which cells happen to be published — the defect this repo keeps
finding when a test's population is the corpus.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2]
REPO = PLUGIN.parents[2]
PROG = PLUGIN / "programs" / "attribution_record_present_check.py"

sys.path.insert(0, str(PLUGIN / "programs"))
import attribution_record_present_check as A  # noqa: E402

APACHE = ("// Copyright 2020 The Example PDK Authors\n"
          "// Licensed under the Apache License, Version 2.0 (the \"License\");\n"
          "module cell(); endmodule\n")
PLAIN = "module generated_thing(); endmodule\n"


def _repo(tmp_path: Path, files: dict) -> Path:
    """A throwaway git repo. Tracked-ness is the unit, so it must be real git."""
    root = tmp_path / "r"
    root.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_CONFIG_SYSTEM": os.devnull}
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, env=env,
                   capture_output=True)
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, env=env,
                   capture_output=True)
    subprocess.run(["git", "-c", "user.email=a@b.invalid", "-c", "user.name=t",
                    "commit", "-q", "-m", "x"], cwd=root, check=True, env=env,
                   capture_output=True)
    return root


# ===========================================================================
# THE TWO DIRECTIONS
# ===========================================================================
def test_a_licenced_file_with_NO_record_FAILS(tmp_path):
    root = _repo(tmp_path, {"benchmark-data/ic/x/rtl/cell.v": APACHE})
    rc, rep = A.audit(root)
    assert rc == 1, rep
    assert rep["counts"]["uncovered"] == 1, rep["counts"]
    f = rep["findings"][0]
    assert f["file"].endswith("cell.v")
    assert "Example PDK Authors" in f["declares"], f["declares"]


def test_PAIRED_the_same_file_WITH_a_record_PASSES(tmp_path):
    """The twin. Without it, "fail on missing attribution" is satisfied by
    failing always."""
    root = _repo(tmp_path, {"benchmark-data/ic/x/rtl/cell.v": APACHE,
                            "benchmark-data/ic/x/SOURCE_MANIFEST.md": "# x\n"})
    rc, rep = A.audit(root)
    assert rc == 0, rep
    assert rep["counts"]["uncovered"] == 0 and rep["counts"]["licenced_files"] == 1


def test_a_record_at_ANY_ancestor_covers_the_file(tmp_path):
    """Coverage is by containment, because that is how an attribution record
    works: it describes the tree it sits at the top of."""
    root = _repo(tmp_path, {"benchmark-data/ic/x/a/b/c/cell.v": APACHE,
                            "benchmark-data/SOURCE_MANIFEST.md": "# all\n"})
    rc, _ = A.audit(root)
    assert rc == 0


def test_a_record_in_a_SIBLING_tree_does_NOT_cover_it(tmp_path):
    """The over-generous reading, refused. A record next door attributes its own
    tree, not this one."""
    root = _repo(tmp_path, {"benchmark-data/ic/x/cell.v": APACHE,
                            "benchmark-data/ic/y/SOURCE_MANIFEST.md": "# y\n"})
    rc, rep = A.audit(root)
    assert rc == 1, rep
    assert rep["findings"][0]["file"].endswith("x/cell.v")


def test_an_UNLICENCED_file_needs_no_record(tmp_path):
    """Flow output is not vendored and carries no obligation. A check that
    demanded a record for generated files would be a ban."""
    root = _repo(tmp_path, {"benchmark-data/ic/x/generated.v": PLAIN,
                            "benchmark-data/ic/x/rtl/cell.v": APACHE,
                            "benchmark-data/ic/x/SOURCE_MANIFEST.md": "# x\n"})
    rc, rep = A.audit(root)
    assert rc == 0
    assert rep["counts"]["licenced_files"] == 1, (
        "the unlicenced file was counted as carrying an obligation")


@pytest.mark.parametrize("record", list(A.RECORD_NAMES))
def test_every_declared_record_name_actually_counts(tmp_path, record):
    """The list is the contract; a name in it that does not work is a trap."""
    root = _repo(tmp_path, {"benchmark-data/ic/x/cell.v": APACHE,
                            f"benchmark-data/ic/x/{record}": "attribution\n"})
    rc, _ = A.audit(root)
    assert rc == 0, f"{record} is in RECORD_NAMES but does not satisfy the check"


@pytest.mark.parametrize("marker", list(A._LICENCE_MARKERS))
def test_every_declared_licence_marker_actually_triggers(tmp_path, marker):
    root = _repo(tmp_path, {"benchmark-data/ic/x/cell.v": f"// {marker}\nmodule m;endmodule\n"})
    rc, rep = A.audit(root)
    assert rc == 1, f"{marker!r} is in _LICENCE_MARKERS but triggers nothing"


# ===========================================================================
# VACUITY
# ===========================================================================
def test_an_empty_scope_REFUSES_rather_than_passing(tmp_path):
    """"I scanned nothing" must not be spelled the same way as "all clear"."""
    root = _repo(tmp_path, {"README.md": "no benchmark data here\n"})
    rc, rep = A.audit(root)
    assert rc == 2, rep
    assert rep["verdict"] == "NO_SCOPE"
    assert "not a pass" in rep["disclosure"]


def test_a_scope_with_NO_licenced_file_also_REFUSES(tmp_path):
    """The subtler vacuity: the roots exist and nothing in them is licenced, so
    zero uncovered is true and means nothing."""
    root = _repo(tmp_path, {"benchmark-data/ic/x/generated.v": PLAIN})
    rc, rep = A.audit(root)
    assert rc == 2, rep
    assert rep["verdict"] == "NO_LICENCED_FILES"


# ===========================================================================
# THE REAL REPOSITORY
# ===========================================================================
@pytest.mark.skipif(not (REPO / "benchmark-data").is_dir(),
                    reason="no benchmark-data in this checkout")
def test_this_repository_attributes_everything_it_vendors():
    """THE ONE THAT WAS RED. On a38902d1 this reported 2 uncovered files —
    39,971 lines of GlobalFoundries PDK cell models and 152,616 lines of
    SkyWater PDK cell models, both Apache-2.0, both vendored with headers
    intact, under an IC directory carrying no record at all.
    """
    rc, rep = A.audit(REPO)
    assert rc == 0, (
        "vendored third-party code is in the tree with no attribution record:\n"
        + "\n".join(f"  {f['file']} declares {f['declares']!r}"
                    for f in rep["findings"]))
    assert rep["counts"]["licenced_files"] > 100, rep["counts"]


@pytest.mark.skipif(not (REPO / "benchmark-data" / "ic" / "spm").is_dir(),
                    reason="spm cell absent")
def test_the_spm_record_names_what_the_files_themselves_declare():
    """An attribution record that invented its facts would be worse than none.

    Each claim here is checked against the vendored file's own header, so the
    record cannot drift from the thing it attributes.
    """
    rec = (REPO / "benchmark-data" / "ic" / "spm" / "SOURCE_MANIFEST.md")
    assert rec.is_file(), "the spm attribution record is gone"
    text = rec.read_text()
    for rel, holder in (
        ("v1.10.18_sky130A/phase2/stage2/dft/cell_model_combined.v",
         "Copyright 2020 The SkyWater PDK Authors"),
        ("v1.9.96_gf180mcuD/phase2/stage2/dft/cell_model_combined.v",
         "Copyright 2022 GlobalFoundries PDK Authors"),
    ):
        src = REPO / "benchmark-data" / "ic" / "spm" / rel
        if not src.is_file():
            pytest.skip(f"{rel} not in this checkout")
        assert holder in src.read_text(errors="replace")[:4000], (
            f"{rel} no longer declares {holder!r}; the record now says "
            f"something the file does not")
        assert rel in text, f"the record does not list {rel}"
        assert holder in text, f"the record does not quote {holder!r}"


def test_the_cli_reports_and_exits_1(tmp_path):
    """The shipped CLI in a subprocess: the exit code is what a gate reads."""
    root = _repo(tmp_path, {"benchmark-data/ic/x/cell.v": APACHE})
    out = tmp_path / "r.json"
    r = subprocess.run([sys.executable, str(PROG), str(root), "--json", str(out)],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert "no attribution record covers it" in r.stdout, r.stdout
    doc = json.loads(out.read_text())
    assert doc["schema"] == A.SCHEMA and doc["verdict"] == "UNATTRIBUTED"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
