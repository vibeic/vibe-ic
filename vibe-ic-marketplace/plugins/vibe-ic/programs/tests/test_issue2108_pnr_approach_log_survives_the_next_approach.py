"""vibe-ic#2108 — a PnR approach must not destroy the previous approach's log.

`step_pnr` composes its OpenROAD command ONCE and re-runs it from a bounded
retry loop (over-util upsize, over-sparse downsize, ROUTING-FEEDBACK loosen
ladder). The command ends `... 2>&1 | tee <out_dir>/openroad.log`, and `tee`
without `-a` truncates its file at open, so approach N destroyed approach
N-1's log before writing a line of its own.

MEASURED on the run that filed the issue: six approaches, five of which
reached `[INFO DRT-0702] Post-route verification: 0 violation(s).`, and the
shipped tree could not show a reader that ANY of them had. The loss is
asymmetric — when a later approach ends worse than an earlier one, the
published record shows only the worse outcome and nothing in the tree
contradicts it.

WHAT THESE TESTS PIN, in both directions:

  1. an earlier approach's evidence is still READABLE from the PnR directory
     after a later approach has run                        (the reproducer);
  2. `openroad.log` itself still carries ONLY the approach that shipped — the
     guard against "fixing" this with `tee -a`, which would let an early
     approach's CTS / crash text vouch for a final approach that never
     produced it;
  3. the archives are NOT swept up by `def_stage_progression_check`'s
     `pnr_dir.rglob("*.log")`, which demotes a `no-routing-geometry` error to
     a warning on a `DETAILED_ROUTE_NONFATAL:` marker found in ANY log there —
     the same laundering as (2), arriving through someone else's glob;
  4. the aggregate names which archive backs which approach; and
  5. a preservation FAILURE is recorded and printed, never swallowed.

No test here launches OpenROAD or a container. The fake `_docker_exec` below
emulates the shell's own `tee` semantics — it parses the tee target and the
`-a` flag out of the command the runner actually built — so the fixture stays
faithful to whichever sink the runner uses rather than to the one this test
was written against.
"""
from __future__ import annotations

import importlib
import json
import re
from pathlib import Path

import pytest

import _hostpaths

mod = importlib.import_module("phase3_one_shot_runner")


# ---------------------------------------------------------------------------
# Fixture: a PnR run that makes two approaches
# ---------------------------------------------------------------------------
_PG_OK = "PG_NET_OWNERSHIP_AUDIT: total=600 no_net=0 masters=\n"

#: Distinguishing text, one line per approach. Neither is a design, PDK or
#: vendor literal; they exist only so a reader of the tree can be asked "is
#: approach 0 still there?" as a MEMBERSHIP question.
_A0_MARK = "APPROACH_ZERO_ONLY_LINE"
_A1_MARK = "APPROACH_ONE_ONLY_LINE"

#: The marker `def_stage_progression_check._is_global_route_only` demotes on.
#: Emitted by approach 0 and NOT by the approach that ships, which is exactly
#: the state that must not be laundered.
_NONFATAL = "DETAILED_ROUTE_NONFATAL: no via-cut rules"

_R0 = (0, ("[INFO DRT-0199] Number of violations = 40.\n"
           "[INFO DRT-0199] Number of violations = 45.\n"
           f"{_NONFATAL}\n{_A0_MARK}\n" + _PG_OK), "")
_R1 = (0, ("[INFO DRT-0199] Number of violations = 0.\n"
           f"{_A1_MARK}\n" + _PG_OK), "")


def _pdk():
    return mod.PdkConfig(
        name="sky130A",
        liberty="/placeholder/sky130_fd_sc_hd__tt.lib",
        tech_lef="/placeholder/sky130_fd_sc_hd.tlef",
        cell_lef="/placeholder/sky130_fd_sc_hd.lef",
        cell_gds="/placeholder/sky130_fd_sc_hd.gds",
        site="unithd", drc_deck="/placeholder/x.drc", metal_prefix="met",
        tapcell_master="sky130_fd_sc_hd__tapvpwrvgnd_1",
        tapcell_distance_um=14.0)


def _build_project(tmp_path: Path, top: str, n_cells: int = 300) -> Path:
    project = tmp_path / "proj"
    docs = project / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "L9_floorplan.md").write_text(
        "| `FP_CORE_UTIL` | **25** |\n"
        "| `PL_TARGET_DENSITY` | **0.30** |\n")
    synth = mod._pl.synth_dir(project)
    synth.mkdir(parents=True, exist_ok=True)
    lines = [f"module {top}(input clk, input a, output y);"]
    for i in range(n_cells):
        lines.append(f"sky130_fd_sc_hd__inv_1 u{i} (.A(n{i}), .Y(n{i + 1}));")
    lines.append("endmodule")
    (synth / f"{top}_synth.v").write_text("\n".join(lines))
    return project


_TEE_RE = re.compile(r"\|\s*tee\s+(?P<append>-a\s+)?(?P<target>\S+)")


def _drive_two_approaches(tmp_path, monkeypatch, top="widget"):
    """Run `step_pnr` with a fake OpenROAD that writes its log THE WAY THE
    RUNNER'S OWN COMMAND SAYS TO — truncating for `| tee`, appending for
    `| tee -a`. Returns (StepResult, project, calls)."""
    project = _build_project(tmp_path, top)
    pnr_dir = mod._pl.pnr_dir(project)
    calls = {"n": 0, "tee_targets": [], "append": []}

    def fake_docker_exec(container, cmd, timeout=None, **_):
        if "openroad -no_init" not in cmd:
            return (0, "", "")
        i = calls["n"]
        calls["n"] += 1
        rc, out, err = (_R0, _R1)[min(i, 1)]
        m = _TEE_RE.search(cmd)
        assert m is not None, f"no tee sink in the route command: {cmd}"
        calls["tee_targets"].append(Path(m.group("target")).name)
        calls["append"].append(bool(m.group("append")))
        # The sink, emulated exactly as the shell would run it.
        sink = pnr_dir / Path(m.group("target")).name
        sink.parent.mkdir(parents=True, exist_ok=True)
        with sink.open("a" if m.group("append") else "w") as fh:
            fh.write(out + err)
        defp = pnr_dir / f"{top}.def"
        defp.write_text("VERSION 5.8 ;\nDESIGN x ;\nEND DESIGN\n")
        return (rc, out, err)

    monkeypatch.setattr(mod, "_docker_exec", fake_docker_exec)
    res = mod.step_pnr(project, top, _pdk(), "iic", "auto", 0.30)
    return res, project, calls


def _files_carrying(project: Path, needle: str):
    """Every file under the PnR directory whose text contains `needle`.

    Deliberately name-agnostic: the question this test asks is "is approach 0
    still readable from this run's tree", not "does a particular filename
    exist", so a different preservation scheme answers it just as well.
    """
    out = []
    for p in sorted(mod._pl.pnr_dir(project).rglob("*")):
        if not p.is_file():
            continue
        try:
            if needle in p.read_text(errors="ignore"):
                out.append(p)
        except OSError:
            continue
    return out


@pytest.fixture()
def two_approaches(tmp_path, monkeypatch):
    res, project, calls = _drive_two_approaches(tmp_path, monkeypatch)
    # The fixture is only a faithful stand-in if the run really made two
    # approaches through one shared sink; assert that before reading anything.
    assert calls["n"] == 2, (calls, res.status, res.detail)
    assert set(calls["tee_targets"]) == {"openroad.log"}, calls["tee_targets"]
    return res, project, calls


# ---------------------------------------------------------------------------
# 1. THE REPRODUCER — the earlier approach's evidence must survive
# ---------------------------------------------------------------------------
class TestEarlierApproachSurvives:
    def test_every_approach_is_still_readable_after_the_last_one_ran(
            self, two_approaches):
        """MEMBERSHIP, not a count and not a bare truthiness.

        The observed value is WHICH approaches are still readable from the run
        tree; the expected value is ALL of them. On the pre-fix runner this
        assertion executes and comes back `['APPROACH_ONE_ONLY_LINE']` — a
        value, and the wrong one — rather than merely noticing that something
        the fix introduces is absent.

        Deliberately name-agnostic: it asks "is approach 0 still readable from
        this run's tree", never "does a particular filename exist", so any
        honest preservation scheme answers it.
        """
        _res, project, _calls = two_approaches
        expected = [_A0_MARK, _A1_MARK]
        readable = [m for m in expected if _files_carrying(project, m)]
        assert readable == expected, (
            "an approach's log is nowhere under phase3/stage3/pnr after a "
            "later approach ran — the shared `| tee` sink truncated it and the "
            "run destroyed its own evidence (vibe-ic#2108)")


# ---------------------------------------------------------------------------
# 2. THE CANONICAL LOG IS STILL ONLY THE APPROACH THAT SHIPPED
# ---------------------------------------------------------------------------
class TestCanonicalLogUnchanged:
    def test_openroad_log_carries_the_last_approach_only(self, two_approaches):
        """`tee -a` is the tempting one-word fix and it is the wrong one.

        Post-loop readers in `phase3_one_shot_runner` are written for "the log
        of the approach that shipped": `_cts_geometrically_complete` accepts a
        CTS breadcrumb found anywhere in this file, and
        `_pnr_fatal_signal_diagnosis` is handed the whole text next to the LAST
        approach's `rc`. Appending would trade a destroyed record for a
        laundered one.
        """
        _res, project, calls = two_approaches
        assert calls["append"] == [False, False], (
            "the route command appends to the shared log — an earlier "
            "approach's text can now vouch for the approach that shipped")
        txt = (mod._pl.pnr_dir(project) / "openroad.log").read_text()
        assert _A1_MARK in txt
        assert _A0_MARK not in txt


# ---------------------------------------------------------------------------
# 3. THE ARCHIVES MUST NOT BE SWEPT UP BY SOMEBODY ELSE'S `*.log` GLOB
# ---------------------------------------------------------------------------
class TestArchivesDoNotLaunderADowngrade:

    def test_no_archive_is_named_like_a_run_log(self, two_approaches):
        _res, project, _calls = two_approaches
        swept = {p.name for p in mod._pl.pnr_dir(project).rglob("*.log")}
        assert swept == {"openroad.log"}, (
            f"a `*.log` sweep of the PnR directory now returns {sorted(swept)}; "
            "every consumer that treats those as 'this run's log' has silently "
            "changed population")


# ---------------------------------------------------------------------------
# 4. THE AGGREGATE NAMES WHICH ARCHIVE BACKS WHICH APPROACH
# ---------------------------------------------------------------------------
class TestApproachManifest:
    def test_manifest_lists_every_approach_and_names_the_canonical_one(
            self, two_approaches):
        _res, project, _calls = two_approaches
        mpath = mod._pl.pnr_dir(project) / mod._PNR_APPROACH_MANIFEST
        assert mpath.is_file(), "no aggregate names the per-approach archives"
        doc = json.loads(mpath.read_text())
        assert doc["canonical_log"] == "openroad.log"
        assert doc["approach_count"] == 2
        assert [r["approach"] for r in doc["approaches"]] == [0, 1]
        assert doc["canonical_log_is_approach"] == 1
        for row in doc["approaches"]:
            assert row["preserved"] is True
            named = mod._pl.pnr_dir(project) / row["log"]
            assert named.is_file(), f"manifest names a missing file: {named}"

    def test_the_named_archive_holds_that_approach_and_no_other(
            self, two_approaches):
        _res, project, _calls = two_approaches
        pnr = mod._pl.pnr_dir(project)
        doc = json.loads((pnr / mod._PNR_APPROACH_MANIFEST).read_text())
        by_i = {r["approach"]: (pnr / r["log"]).read_text() for r in
                doc["approaches"]}
        assert _A0_MARK in by_i[0] and _A1_MARK not in by_i[0]
        assert _A1_MARK in by_i[1] and _A0_MARK not in by_i[1]

    def test_digest_ties_the_canonical_log_to_its_archive(self, two_approaches):
        # The one claim a reader cannot check by eye: that `openroad.log` IS
        # the archive the manifest says it is.
        import hashlib
        _res, project, _calls = two_approaches
        pnr = mod._pl.pnr_dir(project)
        doc = json.loads((pnr / mod._PNR_APPROACH_MANIFEST).read_text())
        last = [r for r in doc["approaches"]
                if r["approach"] == doc["canonical_log_is_approach"]][0]
        assert last["sha256"] == hashlib.sha256(
            (pnr / "openroad.log").read_bytes()).hexdigest()
        assert last["bytes"] == (pnr / "openroad.log").stat().st_size


# ---------------------------------------------------------------------------
# 5. A PRESERVATION FAILURE IS A RECORD, NEVER A SILENCE
# ---------------------------------------------------------------------------
class TestPreservationFailureDegradesLoudly:
    def test_unreadable_source_is_recorded_and_printed(self, tmp_path, capsys):
        out_dir = tmp_path / "pnr"
        out_dir.mkdir()
        history = []
        row = mod._preserve_pnr_approach_log(
            out_dir, out_dir / "openroad.log", 0, 0, history)
        assert row["preserved"] is False
        assert "error" in row and row["error"]
        assert "PNR_APPROACH_LOG_NOT_PRESERVED" in capsys.readouterr().err
        # The manifest still names the approach, carrying the failure.
        doc = json.loads((out_dir / mod._PNR_APPROACH_MANIFEST).read_text())
        assert doc["approaches"][0]["preserved"] is False

    def test_a_failure_does_not_raise_into_the_pnr_verdict(self, tmp_path):
        # The step's verdict is about the DESIGN. An evidence-keeping failure
        # is disclosed, and never converted into a route verdict.
        out_dir = tmp_path / "nonexistent-dir"
        history = []
        row = mod._preserve_pnr_approach_log(
            out_dir, tmp_path / "openroad.log", 3, 137, history)
        assert row["approach"] == 3 and row["rc"] == 137
        assert row["preserved"] is False


# ---------------------------------------------------------------------------
# 6. THE COPY IS FULL — measured against a REAL checked-in artefact
#
# Module-level on purpose: `real_artefact_test_backing_check` builds its
# call graph from `tree.body`, so a test METHOD inside a class can never be
# credited with real-artefact backing however it is written.
# ---------------------------------------------------------------------------
def test_the_archive_is_a_full_copy_of_a_real_in_repo_artefact(tmp_path):
    """Driven by a REAL checked-in file, not by a fixture authored here.

    The property is "a FULL copy, never sampled or truncated", and a
    three-line fixture cannot tell a full copy from a partial one. The
    runner's own source is a real in-repo artefact of real size and is
    resolved through `_hostpaths.require_repo`, so nothing host-specific
    is hardcoded.
    """
    import hashlib
    real = _hostpaths.require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
        "phase3_one_shot_runner.py")
    raw = real.read_bytes()
    assert len(raw) > 100_000, "the real artefact chosen is too small to " \
                               "distinguish a full copy from a partial one"
    out_dir = tmp_path / "pnr"
    out_dir.mkdir()
    row = mod._preserve_pnr_approach_log(out_dir, real, 0, 0, [])
    assert row["preserved"] is True
    archived = (out_dir / row["log"]).read_bytes()
    assert archived == raw
    assert row["bytes"] == len(raw)
    assert row["sha256"] == hashlib.sha256(raw).hexdigest()
