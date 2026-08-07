"""A dangling symlink is a directory entry, not a produced artefact.

DEFECT
------
`flow_compliance_check._glob_first` resolved a step's `required_outputs` and
its `files_exist` gate with `sorted(project.glob(pattern))`. `Path.glob`
serves a WILDCARD component out of `os.scandir` and yields matching NAMES
without following them, so a symlink whose target does not exist came back as
a match and was recorded as the step's evidence.

MEASURED, before the fix, on the tracked run root
`benchmark-data/ic/spm/v1.5.66_gf180mcuD` at real step 1
(`required_outputs: ['phase2/stage1/rtl/*.sv OR phase2/stage1/rtl/*.v', ...]`,
gate `{'files_exist': [...], 'any_of': True}`):

    move every RTL file OUT of the project, leave a symlink to a name that
    exists nowhere  ->  status='PASS'  evidence=['phase2/stage1/rtl/spm.v']
    delete the same files outright                    ->  status='FAIL'

i.e. RTL that exists nowhere in the world scored BETTER than no RTL at all,
purely because a broken link was left behind. Step 37's `required_outputs` is
`('phase3/stage4/gds/*.gds',)`, the same wildcard shape, so the artefact this
reaches at the top of the flow is the tape-out GDS.

The same rule is already shipped for the canonical GDS paths by
`chip_gds_canonical_real_file_check.py`, whose module docstring states the
reason: "Existing `gds_size_check` follows symlinks transparently and reports
the target's size, so a symlink masking a missing tape-out artefact passes
audit."

BIDIRECTIONAL CONTROL
---------------------
Forward (must FAIL against the byte-identical pre-fix file, PASS after):
    test_dangling_symlink_is_not_a_match
    test_dangling_symlink_does_not_satisfy_required_outputs
    test_step37_dangling_gds_is_not_evidence
    test_broken_link_is_never_better_than_deletion

Reverse (must STILL pass — this is what stops the fix degenerating into
"tighten until it fires on nothing"; the owner's step-folder design is a
symlink tree and must keep working):
    test_symlink_to_a_real_file_still_counts
    test_symlink_chain_to_a_real_file_still_counts
    test_symlink_to_a_real_directory_still_counts
    test_plain_real_file_still_counts
    test_reports_subdir_fallback_still_reached_past_a_dangling_link
    test_owner_step_folder_symlink_tree_still_resolves
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest
import yaml

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import flow_compliance_check as FCC  # noqa: E402

_PLUGIN = _PROGRAMS.parent
_FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
# benchmark-data lives at the repo root, three levels above the plugin
# (<repo>/vibe-ic-marketplace/plugins/vibe-ic).
_REPO = _PLUGIN.parents[2]
_SPM = _REPO / "benchmark-data" / "ic" / "spm" / "v1.9.96_gf180mcuD"


def _step(sid):
    doc = yaml.safe_load(_FLOW.read_text())
    steps = doc["steps"] if isinstance(doc, dict) and "steps" in doc else doc
    for s in steps:
        if s.get("id") == sid:
            return s
    raise AssertionError(f"step {sid} not found in {_FLOW}")


# ── Forward control ──────────────────────────────────────────────────────────

def test_dangling_symlink_is_not_a_match(tmp_path):
    """The unit statement of the defect, on the wildcard shape step 37 uses."""
    d = tmp_path / "phase3" / "stage4" / "gds"
    d.mkdir(parents=True)
    link = d / "chip_top.gds"
    os.symlink("../../stage3/pnr/chip_top.gds", link)

    # The link IS a directory entry ...
    assert os.path.lexists(link), "fixture wrong: the symlink was not created"
    # ... and it resolves to nothing.
    assert not link.exists(), "fixture wrong: the target must NOT exist"

    assert FCC._glob_first(tmp_path, "phase3/stage4/gds/*.gds") == [], (
        "a symlink whose target does not exist was returned as a produced "
        "artefact; Path.glob yields the NAME without following it")


def test_dangling_symlink_does_not_satisfy_required_outputs(tmp_path):
    """`check_step` must not accept a link-to-nowhere as delivery."""
    d = tmp_path / "phase3" / "stage4" / "gds"
    d.mkdir(parents=True)
    os.symlink("../../stage3/pnr/chip_top.gds", d / "chip_top.gds")

    step = {"id": 9001, "name": "synthetic", "stage": "stage4",
            "required_outputs": ["phase3/stage4/gds/*.gds"]}
    r = FCC.check_step(tmp_path, step, {})

    assert r.status == "MISSING", (
        f"a step whose only declared output is a broken symlink reported "
        f"{r.status!r}; it produced nothing")
    assert r.evidence == [], (
        f"a broken symlink was recorded as evidence: {r.evidence}")


@pytest.mark.skipif(not _SPM.is_dir(), reason=f"run root absent: {_SPM}")
def test_step37_dangling_gds_is_not_evidence(tmp_path):
    """Real step 37, real run root: the tape-out GDS replaced by a link whose
    target exists nowhere must not be reported as the step's evidence."""
    proj = tmp_path / "proj"
    shutil.copytree(_SPM, proj, symlinks=True)
    gds = proj / "phase3" / "stage4" / "gds" / "chip_top.gds"
    assert gds.is_file(), "fixture wrong: expected a real GDS in the run root"

    # The real bits leave the project entirely.
    shutil.move(str(gds), str(tmp_path / "chip_top.gds.elsewhere"))
    os.symlink("../../stage3/pnr/chip_top.gds", gds)
    assert os.path.lexists(gds) and not gds.exists()

    s37 = _step(37)
    assert s37["required_outputs"] == ["phase3/stage4/gds/*.gds"], (
        "step 37's declared output changed; re-measure this control")

    assert FCC._glob_first(proj, "phase3/stage4/gds/*.gds") == [], (
        "the broken tape-out GDS link still resolves as a produced artefact")

    r = FCC.check_step(proj, s37, {})
    assert "phase3/stage4/gds/chip_top.gds" not in r.evidence, (
        f"step 37 cited a link to a GDS that exists nowhere as its evidence: "
        f"status={r.status!r} evidence={r.evidence}")


@pytest.mark.skipif(not _SPM.is_dir(), reason=f"run root absent: {_SPM}")
def test_broken_link_is_never_better_than_deletion(tmp_path):
    """The asymmetry itself: leaving a link to nothing must not score better
    than deleting the artefact. Real step 1, real run root — the shape that
    reproduced a literal PASS."""
    s1 = _step(1)
    _RANK = {"PASS": 3, "SKIPPED-CONDITION": 2, "WAIVED": 2,
             "FAIL": 1, "MISSING": 0}

    def variant(mode):
        root = tmp_path / mode
        proj = root / "proj"
        shutil.copytree(_SPM, proj, symlinks=True)
        rtl = proj / "phase2" / "stage1" / "rtl"
        files = sorted(p for p in rtl.iterdir() if p.suffix in (".sv", ".v"))
        assert files, "fixture wrong: run root has no RTL"
        for p in files:
            if mode == "dangling":
                shutil.move(str(p), str(root / p.name))  # bits leave the project
                os.symlink(f"./gone_{p.name}", p)        # link to nowhere
            else:
                p.unlink()
        return FCC.check_step(proj, s1, {}), files[0].name

    dang, name = variant("dangling")
    dele, _ = variant("deleted")

    assert f"phase2/stage1/rtl/{name}" not in dang.evidence, (
        f"RTL that exists nowhere was cited as evidence: {dang.evidence}")
    assert _RANK.get(dang.status, 0) <= _RANK.get(dele.status, 0), (
        f"leaving broken links scored BETTER than deleting the files: "
        f"dangling={dang.status!r} vs deleted={dele.status!r}")


# ── Reverse control: what must STILL pass ────────────────────────────────────

def test_plain_real_file_still_counts(tmp_path):
    d = tmp_path / "phase3" / "stage4" / "gds"
    d.mkdir(parents=True)
    (d / "chip_top.gds").write_bytes(b"real bits")
    assert FCC._glob_first(tmp_path, "phase3/stage4/gds/*.gds") == [
        "phase3/stage4/gds/chip_top.gds"]


def test_symlink_to_a_real_file_still_counts(tmp_path):
    """Symlinks are NOT banned. A link to a real file is a produced artefact
    and is judged on what it points at."""
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "chip_top.gds").write_bytes(b"real bits")
    d = tmp_path / "phase3" / "stage4" / "gds"
    d.mkdir(parents=True)
    link = d / "chip_top.gds"
    os.symlink("../../stage3/pnr/chip_top.gds", link)

    assert link.is_symlink() and link.exists()
    assert FCC._glob_first(tmp_path, "phase3/stage4/gds/*.gds") == [
        "phase3/stage4/gds/chip_top.gds"], (
        "a symlink to a REAL file stopped counting — the fix over-tightened "
        "into a symlink ban, which the owner's step-folder tree relies on")
    # "judged on what it actually points at": the read follows through.
    assert link.stat().st_size == len(b"real bits")
    assert link.read_bytes() == b"real bits"


def test_symlink_chain_to_a_real_file_still_counts(tmp_path):
    d = tmp_path / "phase2" / "stage2" / "synth"
    d.mkdir(parents=True)
    (d / "real.v").write_text("module m; endmodule\n")
    os.symlink("./real.v", d / "mid.v")
    os.symlink("./mid.v", d / "netlist.v")
    assert "phase2/stage2/synth/netlist.v" in FCC._glob_first(
        tmp_path, "phase2/stage2/synth/*.v")


def test_symlink_to_a_real_directory_still_counts(tmp_path):
    real = tmp_path / "elsewhere" / "rtl"
    real.mkdir(parents=True)
    (real / "top.v").write_text("module top; endmodule\n")
    (tmp_path / "phase2" / "stage1").mkdir(parents=True)
    os.symlink("../../elsewhere/rtl", tmp_path / "phase2" / "stage1" / "rtl")
    assert FCC._glob_first(tmp_path, "phase2/stage1/rtl/*.v") == [
        "phase2/stage1/rtl/top.v"]
    assert FCC._glob_first(tmp_path, "phase2/stage1/*") == [
        "phase2/stage1/rtl"], "a symlinked DIRECTORY stopped resolving"


def test_reports_subdir_fallback_still_reached_past_a_dangling_link(tmp_path):
    """A dangling link at the FLAT reports/ location must not suppress the
    `reports/<subdir>/` fallback probe. This is why the filter is applied at
    each probe site rather than once over the final result."""
    (tmp_path / "reports").mkdir()
    os.symlink("./gone.json", tmp_path / "reports" / "drc.json")
    sub = tmp_path / "reports" / "phase3"
    sub.mkdir()
    (sub / "drc.json").write_text("{}")

    assert FCC._glob_first(tmp_path, "reports/drc.json") == [
        "reports/phase3/drc.json"], (
        "the broken flat-location link swallowed the subdir fallback and "
        "hid a report that really exists")


@pytest.mark.skipif(not _SPM.is_dir(), reason=f"run root absent: {_SPM}")
def test_owner_step_folder_symlink_tree_still_resolves(tmp_path):
    """The owner's step-folder design is a symlink tree. State plainly what
    this rule does to it: every link that points at a real file still
    resolves; only links that point at nothing stop counting."""
    proj = tmp_path / "proj"
    shutil.copytree(_SPM, proj, symlinks=True)
    steps_dir = proj / "steps"
    steps_dir.mkdir(exist_ok=True)
    d = steps_dir / "9_synthesis"
    d.mkdir()
    # Two links of the exact production shape, one healthy, one broken.
    (proj / "phase2" / "stage2" / "synth").mkdir(parents=True, exist_ok=True)
    (proj / "phase2" / "stage2" / "synth" / "present.v").write_text("// bits\n")
    os.symlink("../../phase2/stage2/synth/present.v", d / "healthy.v")
    os.symlink("../../phase2/stage2/synth/absent.v", d / "broken.v")

    hits = FCC._glob_first(proj, "steps/9_synthesis/*.v")
    assert "steps/9_synthesis/healthy.v" in hits, (
        "a step-folder link to a real artefact stopped resolving — this rule "
        "must not break the symlink-tree design")
    assert "steps/9_synthesis/broken.v" not in hits, (
        "a step-folder link to an artefact that exists nowhere still counted")
