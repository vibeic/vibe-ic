"""vibe-ic#2133 — a second `step_pnr` into one out_dir must not destroy the
first invocation's approach archives.

vibe-ic#2108 closed the loss WITHIN one invocation: each approach's
`openroad.log` is archived beside the canonical log before the next `| tee`
truncates it. The archive index is `_retry_i`, which is local to ONE
`step_pnr` call and RESTARTS AT 0 on the next one — and `step_pnr` is called
more than once into the SAME out_dir: `main` re-dispatches it after the PDN-EM
first-pass resize. So invocation N's approach 0 landed on top of invocation
N-1's approach 0, and the rest of invocation N-1's archives were orphaned from
a manifest that no longer mentioned them.

MEASURED on the run that filed the issue (an open PDK, a real front-door run,
2026-09-07): 12:37 wrote `approach0` sha b545fd04... 7913 B and `approach1`
100012 B carrying the two `[INFO DRT-0702] Post-route verification: 0
violation(s).` lines — the proof the design routed clean; 12:44 wrote
`approach0` sha 87ae65dd..., ALSO 7913 B; at 13:01 `approach1` went 100012 ->
242545 B. Two facts make this a reporting-integrity defect rather than an
untidy directory:

  * both approach-0 files were the SAME SIZE, so no size and no count could
    see the loss — only a digest can; and
  * the manifest stayed internally SELF-CONSISTENT throughout (its recorded
    sha always equalled the file then on disk), so nothing in the tree
    signalled that a record had been destroyed.

Every assertion below that asks "is the earlier record still there" therefore
asks it with sha256, never with a size and never with a count.

WHAT THESE TESTS PIN, in both directions:

  1. two invocations into one out_dir keep BOTH archive sets, byte-identical
     to what each invocation wrote                          (the reproducer);
  2. the manifest references every invocation's approaches and names which
     invocation, and which approach of it, `openroad.log` duplicates;
  3. the first invocation's DRT-0702 evidence is reachable BY THE MANIFEST —
     not merely still somewhere on disk as an orphan;
  4. MUTATION: restart the invocation index (the pre-fix behaviour) and the
     second write is REFUSED by name — red if it silently overwrites;
  5. a directory an OLDER plugin wrote (pre-#2133 archive names) is recognised
     as invocation 0 and is not overwritten; and
  6. #2108's own invariants still hold across two invocations: `openroad.log`
     carries only the approach that shipped, and a `*.log` sweep of the PnR
     directory has not changed population.

THE COMPLETE CONSUMER SET of `openroad.approaches.json` at the time of writing,
established by `grep -rn "approaches\\.json\\|_PNR_APPROACH_MANIFEST\\|
_PNR_APPROACH_LOG_FMT\\|openroad\\.approach" .` over the whole repository, and
bound below over the plugin's `*.py` / `*.md` SOURCES:
`phase3_one_shot_runner.py` (the producer),
`test_issue2108_pnr_approach_log_survives_the_next_approach.py`, and this
module. Two further files NAME the archives in prose without reading them:
`def_stage_progression_check.py` and
`test_issue2116_global_route_marker_reads_only_the_canonical_log.py`, both of
which recount why #2108 chose the `.txt` suffix. No program reads the manifest
or the archives outside the three above, and no sweep of the PnR directory
reaches them: `def_stage_progression_check` swept `pnr_dir.rglob("*.log")`
until vibe-ic#2116 narrowed it to `rglob("openroad.log")`, so the archives are
outside it under BOTH the `.txt` suffix #2108 gave them and the narrowed glob.
`test_the_manifest_consumer_set_is_still_what_this_module_names` below binds
the whole set so it cannot rot silently.

No test here launches OpenROAD or a container. The fake `_docker_exec` below
emulates the shell's own `tee` semantics — it parses the tee target and the
`-a` flag out of the command the runner actually built — so the fixture stays
faithful to whichever sink the runner uses rather than to the one this test
was written against.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import re
import subprocess
from pathlib import Path

import pytest

import _hostpaths

mod = importlib.import_module("phase3_one_shot_runner")


# ---------------------------------------------------------------------------
# Fixture: TWO `step_pnr` invocations into ONE out_dir
# ---------------------------------------------------------------------------
_PG_OK = "PG_NET_OWNERSHIP_AUDIT: total=600 no_net=0 masters=\n"

#: The line whose loss is the issue. Emitted by invocation 0's SECOND approach
#: and by nothing else, so "is it reachable from the manifest" is a MEMBERSHIP
#: question about the invocation that no longer ships.
_DRT_CLEAN = "[INFO DRT-0702] Post-route verification: 0 violation(s)."

#: The marker `def_stage_progression_check._is_global_route_only` demotes on.
_NONFATAL = "DETAILED_ROUTE_NONFATAL: no via-cut rules"

#: One distinguishing line per (invocation, approach). Neither a design, a PDK
#: nor a vendor literal. The two `approach0` bodies are deliberately the SAME
#: LENGTH and different content, which is the shape the issue measured: two
#: 7913-byte files where only a digest can tell the loss.
_MARK = {
    (0, 0): "INVOCATION_ZERO_APPROACH_ZERO_LINE",
    (0, 1): "INVOCATION_ZERO_APPROACH_ONE_LINE_",
    (1, 0): "INVOCATION_ONE__APPROACH_ZERO_LINE",
    (1, 1): "INVOCATION_ONE__APPROACH_ONE_LINE_",
}

_TEE_RE = re.compile(r"\|\s*tee\s+(?P<append>-a\s+)?(?P<target>\S+)")


def _body(inv: int, approach: int) -> str:
    """The fake tool's stdout for one approach of one invocation.

    ONLY invocation 0's shipping approach reaches a clean post-route
    verification. That asymmetry IS the issue: the invocation that ends up
    shipping produced no such proof, so the archive of the one that did is the
    whole of the evidence that the design ever routed clean — and it is the
    file the second invocation overwrote.
    """
    if approach == 0:
        head = ("[INFO DRT-0199] Number of violations = 40.\n"
                + _NONFATAL + "\n")
    elif inv == 0:
        head = ("[INFO DRT-0199] Number of violations = 0.\n"
                + _DRT_CLEAN + "\n" + _DRT_CLEAN + "\n")
    else:
        head = "[INFO DRT-0199] Number of violations = 0.\n"
    return head + _MARK[(inv, approach)] + "\n" + _PG_OK


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


def _sha_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digests(pnr_dir: Path) -> dict:
    """sha256 of every file under the PnR directory, keyed by name."""
    return {p.name: _sha_of(p)
            for p in sorted(pnr_dir.rglob("*")) if p.is_file()}


class _Rig:
    """Drives `step_pnr` repeatedly into one project with a fake OpenROAD that
    writes its log THE WAY THE RUNNER'S OWN COMMAND SAYS TO — truncating for
    `| tee`, appending for `| tee -a`."""

    def __init__(self, tmp_path, monkeypatch, top="widget"):
        self.top = top
        self.project = _build_project(tmp_path, top)
        self.pnr_dir = mod._pl.pnr_dir(self.project)
        self.invocation = -1
        self.calls = 0
        self.tee_targets = []
        self.append_flags = []
        monkeypatch.setattr(mod, "_docker_exec", self._fake_docker_exec)

    def _fake_docker_exec(self, container, cmd, timeout=None, **_):
        if "openroad -no_init" not in cmd:
            return (0, "", "")
        approach = self.calls
        self.calls += 1
        out = _body(self.invocation, min(approach, 1))
        m = _TEE_RE.search(cmd)
        assert m is not None, f"no tee sink in the route command: {cmd}"
        self.tee_targets.append(Path(m.group("target")).name)
        self.append_flags.append(bool(m.group("append")))
        sink = self.pnr_dir / Path(m.group("target")).name
        sink.parent.mkdir(parents=True, exist_ok=True)
        with sink.open("a" if m.group("append") else "w") as fh:
            fh.write(out)
        (self.pnr_dir / f"{self.top}.def").write_text(
            "VERSION 5.8 ;\nDESIGN x ;\nEND DESIGN\n")
        return (0, out, "")

    def invoke(self):
        """One `step_pnr` call. Returns its StepResult."""
        self.invocation += 1
        self.calls = 0
        res = mod.step_pnr(self.project, self.top, _pdk(), "iic", "auto", 0.30)
        assert self.calls == 2, (
            f"invocation {self.invocation} made {self.calls} approaches, not "
            f"2 — the fixture is not the two-approach shape it claims to be: "
            f"{res.status} {res.detail}")
        return res

    def manifest(self) -> dict:
        return json.loads(
            (self.pnr_dir / mod._PNR_APPROACH_MANIFEST).read_text())

    def manifest_invocations(self) -> list:
        """The manifest's per-invocation view, TOLERANT of a manifest that has
        no `invocations` field at all.

        Written this way ON PURPOSE. A manifest with no `invocations` key
        describes exactly one invocation, and reading it that way is what lets
        the PRE-FIX producer ANSWER these questions — wrongly — instead of
        raising `KeyError`. An error is not an answer: a control whose every
        failure is an absence proves only that the code under test is new,
        which is true of every new file ever written.
        """
        doc = self.manifest()
        invs = doc.get("invocations")
        if not isinstance(invs, list):
            invs = [{"invocation": doc.get("canonical_invocation", 0),
                     "canonical": True,
                     "approaches": doc.get("approaches") or []}]
        return invs

    def manifest_named_files(self) -> dict:
        """Every archive the manifest names, mapped to its recorded sha256.

        Reads the per-invocation view, which is the field that must carry
        EVERY invocation. A row is included only when the manifest itself says
        it was preserved, so a refusal cannot be read as a promise.
        """
        out = {}
        for inv in self.manifest_invocations():
            for row in inv.get("approaches") or []:
                if row.get("preserved"):
                    out[row["log"]] = row.get("sha256")
        return out

    def manifest_marks(self) -> dict:
        """{(invocation, approach) -> the marks readable in the file the
        manifest names for it}. The observed half of the membership question
        this module keeps asking."""
        out = {}
        for inv in self.manifest_invocations():
            for row in inv.get("approaches") or []:
                try:
                    txt = (self.pnr_dir / row["log"]).read_text(errors="ignore")
                except OSError:
                    txt = ""
                out[(inv.get("invocation"), row.get("approach"))] = sorted(
                    m for m in _MARK.values() if m in txt)
        return out


@pytest.fixture()
def two_invocations(tmp_path, monkeypatch):
    """Two `step_pnr` calls into ONE out_dir, with the tree digested between
    them. Returns (rig, digests_after_first)."""
    rig = _Rig(tmp_path, monkeypatch)
    rig.invoke()
    after_first = _digests(rig.pnr_dir)
    rig.invoke()
    return rig, after_first


# ---------------------------------------------------------------------------
# 0. THE FIXTURE IS THE SHAPE THE ISSUE MEASURED
# ---------------------------------------------------------------------------
def test_the_two_approach_zero_logs_are_the_same_size_and_differ(
        two_invocations):
    """The issue's load-bearing detail: both invocations' approach-0 logs were
    7913 bytes, so a size or a count check was BLIND to the loss.

    If this fixture ever stops producing equal-length, different-content
    approach-0 bodies, every assertion below silently becomes a weaker test
    than it reads as — a size check would start catching what only a digest
    is supposed to catch.
    """
    a, b = _body(0, 0), _body(1, 0)
    assert len(a) == len(b), (len(a), len(b))
    assert a != b


# ---------------------------------------------------------------------------
# 1. THE REPRODUCER — the first invocation's archives survive the second
# ---------------------------------------------------------------------------
class TestFirstInvocationArchivesSurvive:
    def test_every_archive_the_first_invocation_wrote_is_byte_identical_after(
            self, two_invocations):
        """MEMBERSHIP of an observed digest map against an expected one.

        The observed value is {archive name -> sha256} for every archive that
        existed after invocation 0, re-read after invocation 1. The expected
        value is the same map unchanged. On the pre-fix runner this assertion
        EXECUTES and comes back with different digests under the same names —
        a value, and the wrong one — rather than noticing that something the
        fix introduces is absent.
        """
        rig, after_first = two_invocations
        archives_before = {n: s for n, s in after_first.items()
                           if n.endswith(".log.txt")}
        assert archives_before, (
            "invocation 0 archived nothing — the fixture never reached the "
            "preservation path and nothing below is measuring #2133")
        now = _digests(rig.pnr_dir)
        observed = {n: now.get(n) for n in archives_before}
        assert observed == archives_before, (
            "an archive written by the first `step_pnr` invocation changed "
            "under the second — invocation N's approach index restarted at 0 "
            "and overwrote invocation N-1's archive (vibe-ic#2133)")

    def test_both_invocations_marks_are_readable_from_the_run_tree(
            self, two_invocations):
        """Name-agnostic MEMBERSHIP: which (invocation, approach) bodies are
        still readable anywhere under the PnR directory. Any honest
        preservation scheme answers it; none of it depends on a filename."""
        rig, _after_first = two_invocations
        texts = [p.read_text(errors="ignore")
                 for p in sorted(rig.pnr_dir.rglob("*")) if p.is_file()]
        expected = sorted(_MARK.values())
        readable = sorted(m for m in _MARK.values()
                          if any(m in t for t in texts))
        assert readable == expected


# ---------------------------------------------------------------------------
# 2. THE MANIFEST REFERENCES EVERY INVOCATION
# ---------------------------------------------------------------------------
class TestManifestCoversEveryInvocation:
    def test_manifest_names_both_invocations_and_all_their_archives(
            self, two_invocations):
        rig, after_first = two_invocations
        assert [i.get("invocation") for i in rig.manifest_invocations()] \
            == [0, 1], (
            "the manifest does not describe two invocations — the second "
            "`step_pnr` call rewrote it as if it were the only one that ever "
            "ran in this directory (vibe-ic#2133)")
        named = rig.manifest_named_files()
        on_disk = {n for n in _digests(rig.pnr_dir) if n.endswith(".log.txt")}
        assert set(named) == on_disk, (
            "the manifest and the archives on disk disagree — an archive the "
            "manifest does not name is an orphan no reader can find, and a "
            "name with no file is a promise the tree cannot keep")
        for name, recorded in named.items():
            assert recorded == _sha_of(rig.pnr_dir / name), (
                f"{name}: the manifest's recorded digest is not the file's")

    def test_manifest_names_the_canonical_invocation_and_approach(
            self, two_invocations):
        """`openroad.log` is whatever the LAST approach of the LAST invocation
        left behind. With two invocations in one directory, naming the
        approach is no longer enough to identify it."""
        rig, _after_first = two_invocations
        pnr, doc = rig.pnr_dir, rig.manifest()
        # Every field read with `.get`, so the pre-fix manifest answers with a
        # VALUE rather than raising — see `_Rig.manifest_invocations`.
        observed = {
            "canonical_log": doc.get("canonical_log"),
            "canonical_invocation": doc.get("canonical_invocation"),
            "canonical_log_is_approach": doc.get("canonical_log_is_approach"),
            "canonical_archive": doc.get("canonical_archive"),
            "canonical_invocations": [i.get("invocation") for i
                                      in rig.manifest_invocations()
                                      if i.get("canonical")],
        }
        assert observed == {
            "canonical_log": "openroad.log",
            "canonical_invocation": 1,
            "canonical_log_is_approach": 1,
            "canonical_archive": doc["approaches"][-1]["log"],
            "canonical_invocations": [1],
        }
        assert _sha_of(pnr / observed["canonical_archive"]) == _sha_of(
            pnr / "openroad.log")

    def test_the_named_archive_holds_that_invocations_approach_only(
            self, two_invocations):
        rig, _after_first = two_invocations
        observed = rig.manifest_marks()
        expected = {key: [mark] for key, mark in _MARK.items()}
        assert observed == expected, (
            "the file the manifest names for an (invocation, approach) does "
            "not hold that approach's text and nothing else — an archive was "
            "overwritten by a later invocation (vibe-ic#2133)")


# ---------------------------------------------------------------------------
# 3. THE DRT-0702 EVIDENCE OF THE FIRST INVOCATION IS REACHABLE BY THE MANIFEST
# ---------------------------------------------------------------------------
class TestFirstInvocationRouteEvidenceStaysReachable:
    def test_the_clean_post_route_lines_are_found_through_the_manifest(
            self, two_invocations):
        """The issue's concrete loss. Invocation 0's approach 1 is the ONLY
        thing carrying the two clean post-route lines; invocation 1 never
        produced them. "Still on disk" is not enough — an orphan the manifest
        does not name is not evidence a reader can find. So this walks the
        manifest and asks which of the files IT names carries them.
        """
        rig, _after_first = two_invocations
        pnr = rig.pnr_dir
        # OBSERVED: for each (invocation, approach) the manifest names, how
        # many clean post-route lines that file carries. EXPECTED: exactly the
        # two that invocation 0's approach 1 emitted, and none anywhere else.
        observed = {}
        for inv in rig.manifest_invocations():
            for row in inv.get("approaches") or []:
                try:
                    txt = (pnr / row["log"]).read_text(errors="ignore")
                except OSError:
                    txt = ""
                observed[(inv.get("invocation"), row.get("approach"))] = \
                    txt.count(_DRT_CLEAN)
        expected = {key: (2 if key == (0, 1) else 0) for key in _MARK}
        assert observed == expected, (
            "the manifest no longer reaches a file carrying the first "
            f"invocation's {_DRT_CLEAN!r} — the proof the design routed clean "
            "is destroyed or orphaned (vibe-ic#2133)")


# ---------------------------------------------------------------------------
# 4. MUTATION — RESTART THE INDEX AND THE WRITE IS REFUSED, NOT SILENT
# ---------------------------------------------------------------------------
class TestRestartingTheIndexIsRefused:
    def test_a_second_invocation_that_restarts_the_index_is_refused_by_name(
            self, tmp_path, monkeypatch, capsys):
        """THE MUTATION IS THE PRE-FIX BEHAVIOUR, injected deliberately.

        `_next_pnr_invocation_index` is forced back to 0 for the second
        invocation, which is exactly what the runner did before #2133. The
        archives must NOT change; the refusal must be recorded and printed.
        A silent overwrite here is the defect and this test goes red on it.
        """
        rig = _Rig(tmp_path, monkeypatch)
        rig.invoke()
        after_first = _digests(rig.pnr_dir)
        archives_before = {n: s for n, s in after_first.items()
                           if n.endswith(".log.txt")}
        assert archives_before

        monkeypatch.setattr(mod, "_next_pnr_invocation_index",
                            lambda _out_dir: 0)
        capsys.readouterr()
        rig.invoke()
        err = capsys.readouterr().err

        now = _digests(rig.pnr_dir)
        assert {n: now.get(n) for n in archives_before} == archives_before, (
            "the invocation index restarted at 0 and the runner SILENTLY "
            "overwrote the first invocation's archives — the refusal did not "
            "fire (vibe-ic#2133)")
        assert "PNR_APPROACH_ARCHIVE_REFUSED_OVERWRITE" in err, (
            "the collision was not announced; a refusal nobody can see is "
            "indistinguishable from the overwrite it replaced")
        rows = rig.manifest()["approaches"]
        assert [r["refused"] for r in rows] == [True, True], rows
        assert all(r["preserved"] is False for r in rows), rows
        assert all("PNR_APPROACH_ARCHIVE_EXISTS" in r["error"] for r in rows)

    def test_a_refused_canonical_approach_is_not_claimed_as_the_archive(
            self, tmp_path, monkeypatch):
        """`canonical_archive` must go None rather than point at a file that
        belongs to somebody else. A refusal that still names an archive would
        be a fresh lie inside the record written to stop one."""
        rig = _Rig(tmp_path, monkeypatch)
        rig.invoke()
        monkeypatch.setattr(mod, "_next_pnr_invocation_index",
                            lambda _out_dir: 0)
        rig.invoke()
        doc = rig.manifest()
        assert doc["canonical_archive"] is None
        assert doc["canonical_log_is_approach"] == 1

    def test_the_refusal_does_not_change_the_pnr_verdict(
            self, tmp_path, monkeypatch):
        """ADVISORY / DISCLOSURE-ONLY, proved rather than declared. The step's
        verdict is about the DESIGN; an evidence-keeping refusal is disclosed
        and never converted into a route verdict."""
        rig_a = _Rig(tmp_path / "a", monkeypatch)
        rig_a.invoke()
        clean = rig_a.invoke()
        rig_b = _Rig(tmp_path / "b", monkeypatch)
        rig_b.invoke()
        monkeypatch.setattr(mod, "_next_pnr_invocation_index",
                            lambda _out_dir: 0)
        refused = rig_b.invoke()
        assert refused.status == clean.status
        assert refused.detail == clean.detail


# ---------------------------------------------------------------------------
# 5. THE INVOCATION KEY IS DERIVED FROM DISK, AND DEGRADES LOUDLY
# ---------------------------------------------------------------------------
class TestInvocationIndexDerivation:
    def test_an_empty_directory_is_invocation_zero(self, tmp_path):
        assert mod._next_pnr_invocation_index(tmp_path) == 0

    def test_archives_alone_are_enough_when_the_manifest_is_gone(
            self, two_invocations):
        """A manifest can be deleted while the archives it named remain. The
        key must come from the files too, or the next invocation collides."""
        rig, _after_first = two_invocations
        (rig.pnr_dir / mod._PNR_APPROACH_MANIFEST).unlink()
        assert mod._next_pnr_invocation_index(rig.pnr_dir) == 2

    def test_the_manifest_alone_is_enough_when_the_archives_are_gone(
            self, two_invocations):
        """And the mirror case: a partially copied tree carrying a manifest
        whose files did not come with it."""
        rig, _after_first = two_invocations
        for p in rig.pnr_dir.glob("*.log.txt"):
            p.unlink()
        assert mod._next_pnr_invocation_index(rig.pnr_dir) == 2

    def test_a_directory_written_by_an_older_plugin_is_invocation_zero(
            self, tmp_path):
        """A tree an older plugin wrote carries `openroad.approach0.log.txt`
        with no invocation key. It IS invocation 0, so the next invocation is
        1 and nothing pre-#2133 is overwritten."""
        out = tmp_path / "pnr"
        out.mkdir()
        (out / "openroad.approach0.log.txt").write_text("legacy 0\n")
        (out / "openroad.approach1.log.txt").write_text("legacy 1\n")
        (out / mod._PNR_APPROACH_MANIFEST).write_text(json.dumps({
            "canonical_log": "openroad.log",
            "canonical_log_is_approach": 1,
            "approach_count": 2,
            "approaches": [
                {"approach": 0, "log": "openroad.approach0.log.txt",
                 "rc": 1, "preserved": True},
                {"approach": 1, "log": "openroad.approach1.log.txt",
                 "rc": 0, "preserved": True},
            ]}) + "\n")
        assert mod._next_pnr_invocation_index(out) == 1

    def test_a_legacy_tree_survives_the_next_invocation_intact(self, tmp_path):
        """End to end on the legacy shape: the pre-#2133 archives keep their
        digests, and the new manifest carries them forward under invocation 0
        instead of dropping them."""
        out = tmp_path / "pnr"
        out.mkdir()
        (out / "openroad.approach0.log.txt").write_text("legacy zero body\n")
        (out / "openroad.approach1.log.txt").write_text("legacy one body\n")
        (out / mod._PNR_APPROACH_MANIFEST).write_text(json.dumps({
            "canonical_log": "openroad.log",
            "canonical_log_is_approach": 1,
            "approach_count": 2,
            "approaches": [
                {"approach": 0, "log": "openroad.approach0.log.txt",
                 "rc": 1, "preserved": True},
                {"approach": 1, "log": "openroad.approach1.log.txt",
                 "rc": 0, "preserved": True},
            ]}) + "\n")
        before = {p.name: _sha_of(p) for p in out.glob("*.log.txt")}
        src = out / "openroad.log"
        src.write_text("new invocation body\n")
        inv = mod._next_pnr_invocation_index(out)
        mod._preserve_pnr_approach_log(out, src, 0, 0, [], invocation=inv)
        assert {p.name: _sha_of(p) for p in out.glob("*.log.txt")
                if p.name in before} == before
        doc = json.loads((out / mod._PNR_APPROACH_MANIFEST).read_text())
        carried = [i for i in doc["invocations"] if i["invocation"] == 0][0]
        assert [r["log"] for r in carried["approaches"]] == [
            "openroad.approach0.log.txt", "openroad.approach1.log.txt"]
        assert carried["canonical"] is False

    def test_an_unreadable_directory_says_so_and_the_refusal_covers_it(
            self, tmp_path, capsys):
        """Guessing LOW is the unsafe direction, so it is announced — and the
        refusal, not this number, is what actually stops the overwrite."""
        missing = tmp_path / "not-there"
        assert mod._next_pnr_invocation_index(missing) == 0
        assert "PNR_APPROACH_INVOCATION_INDEX_UNDERIVED" in \
            capsys.readouterr().err

    def test_a_row_whose_archive_has_gone_is_dropped_not_promised(
            self, two_invocations):
        """A carried-forward row must name a file that is still there. A
        record that quietly shrinks is this defect wearing the other hat, so
        the drop is COUNTED."""
        rig, _after_first = two_invocations
        doc = rig.manifest()
        gone = rig.manifest_invocations()[0]["approaches"][0]["log"]
        (rig.pnr_dir / gone).unlink()
        mod._write_pnr_approach_manifest(
            rig.pnr_dir, list(doc["approaches"]), 1)
        after = rig.manifest()
        inv0 = [i for i in after["invocations"] if i["invocation"] == 0][0]
        assert gone not in [r["log"] for r in inv0["approaches"]]
        assert inv0["approaches_dropped_absent"] == 1


# ---------------------------------------------------------------------------
# 6. #2108's INVARIANTS STILL HOLD ACROSS TWO INVOCATIONS
# ---------------------------------------------------------------------------
class TestIssue2108InvariantsHoldAcrossInvocations:
    def test_openroad_log_carries_the_last_approach_only(self, two_invocations):
        rig, _after_first = two_invocations
        # Four approaches across the two invocations, none of them appending.
        assert rig.append_flags == [False] * 4, (
            "the route command appends to the shared log — an earlier "
            "approach's text can now vouch for the approach that shipped")
        txt = (rig.pnr_dir / "openroad.log").read_text()
        assert _MARK[(1, 1)] in txt
        assert [m for m in _MARK.values() if m in txt] == [_MARK[(1, 1)]]

    def test_no_archive_is_named_like_a_run_log(self, two_invocations):
        rig, _after_first = two_invocations
        swept = {p.name for p in rig.pnr_dir.rglob("*.log")}
        assert swept == {"openroad.log"}, (
            f"a `*.log` sweep of the PnR directory now returns {sorted(swept)};"
            " every consumer that treats those as 'this run's log' has "
            "silently changed population")


# ---------------------------------------------------------------------------
# 7. THE CONSUMER SET NAMED IN THIS MODULE'S DOCSTRING IS STILL COMPLETE
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 8. THE REFUSAL KEEPS THE EXISTING ARCHIVE WHOLE — on a REAL artefact
#
# Module-level on purpose: `real_artefact_test_backing_check` builds its call
# graph from `tree.body`, so a test METHOD inside a class can never be
# credited with real-artefact backing however it is written.
# ---------------------------------------------------------------------------
def test_a_refusal_leaves_a_real_in_repo_artefact_byte_identical(tmp_path):
    """A refusal must keep the existing archive WHOLE, not merely present.

    Driven by a real checked-in file of real size, because a three-line
    fixture cannot tell an untouched file from one that was truncated at open
    and then not written — which is the exact failure mode `| tee` gave this
    subsystem in the first place.
    """
    real = _hostpaths.require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
        "phase3_one_shot_runner.py")
    raw = real.read_bytes()
    assert len(raw) > 100_000, "the real artefact chosen is too small to " \
                               "distinguish a whole file from a truncated one"
    out_dir = tmp_path / "pnr"
    out_dir.mkdir()
    first = mod._preserve_pnr_approach_log(out_dir, real, 0, 0, [],
                                           invocation=0)
    assert first["preserved"] is True and first["refused"] is False
    archived = out_dir / first["log"]
    assert archived.read_bytes() == raw

    other = tmp_path / "other.log"
    other.write_text("a different, much shorter approach\n")
    second = mod._preserve_pnr_approach_log(out_dir, other, 0, 0, [],
                                            invocation=0)
    assert second["refused"] is True and second["preserved"] is False
    assert archived.read_bytes() == raw
    assert hashlib.sha256(archived.read_bytes()).hexdigest() == \
        hashlib.sha256(raw).hexdigest()
