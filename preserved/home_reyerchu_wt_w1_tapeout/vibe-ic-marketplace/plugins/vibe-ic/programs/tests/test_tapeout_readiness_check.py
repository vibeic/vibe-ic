"""Unit tests for `tapeout_readiness_check.py` — the LIVE open-MPW submission gate.

WHAT THESE TESTS ARE FOR
========================
The gate's whole value is that its verdict is NOT ours: it runs the shuttle's own
precheck container and fails on that container's exit code.  So the things worth
testing here are not layout rules — the module deliberately contains none — but
the four properties that decide whether the wrapper can be trusted:

  1. the image is pinned by DIGEST, and a tag is refused rather than run;
  2. the graded run can never reach the network, and can never be told to run
     fewer of the shuttle's checks;
  3. "could not run" is its OWN state, it FAILS the gate, and it can never be
     rendered as "no refusals found" — including the most dangerous case of all,
     a ZERO exit that produced no evidence;
  4. the stage accounting is "3 of 16" with the un-run stages NAMED, and every
     field degrades to NOT_DETERMINED rather than to a plausible number.

`FakeDocker` below stands in for the container so that every state above is
reachable with no live image.  It dispatches on the argv the module actually
builds — probe / pull / enumerate / graded run — and, for the graded run, writes
the numbered step directories into the same host directory the real container
would write them to.  So the command construction and the evidence read-back are
both under test, not just the branch logic.
"""
from __future__ import annotations

import ast
import importlib
import json
import re
from pathlib import Path

import pytest

from _source_pin import func_src

mod = importlib.import_module("tapeout_readiness_check")


def _code_only(src: str) -> str:
    """`src` with comments and docstrings removed, so a source assertion pins
    what the program DOES rather than what it explains about itself.

    Written after the first draft of these tests failed on their own prose: the
    module's docstring names the container's steps in order to say that it does
    not carry them, and a raw text scan cannot tell an explanation from a rule.
    """
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", None)
        if body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def _cli_option_strings(src: str) -> list:
    """Every option string the module's argparse actually accepts."""
    opts = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "add_argument":
            for a in node.args:
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    opts.append(a.value)
    return opts


# The container's real 16-step ladder, as the container itself reports it.
# It lives HERE, in the test, on purpose: the program must never carry a copy of
# it, because a built-in ladder is the program quietly reimplementing the thing
# it exists to wrap.  A test may hold a fixture; the gate may not hold a rule.
LADDER = [
    ("KLayout.ReadLayout", "Read the Layout"),
    ("KLayout.CheckTopLevel", "Check Top-Level Name"),
    ("KLayout.CheckSize", "Check Slot Size"),
    ("KLayout.GenerateID", "Generate ID"),
    ("KLayout.Render", "Render Image (w/ KLayout)"),
    ("KLayout.Density", "Density Check"),
    ("Checker.KLayoutDensity", "KLayout Density Checker"),
    ("KLayout.ZeroAreaPolygons", "Find Zero Area Polygons"),
    ("Checker.KLayoutZeroAreaPolygons", "KLayout Zero Area Polygons Checker"),
    ("KLayout.Antenna", "Antenna Check"),
    ("Checker.KLayoutAntenna", "KLayout Antenna Checker"),
    ("Magic.DRC", "DRC"),
    ("Checker.MagicDRC", "Magic DRC Checker"),
    ("KLayout.DRC", "Design Rule Check (KLayout)"),
    ("Checker.KLayoutDRC", "KLayout DRC Checker"),
    ("KLayout.WriteLayout", "Write the Layout"),
]

# The measured refusal from the shuttle's own error.log on a real published GDS.
REAL_REFUSAL = (
    "Subprocess had a non-zero exit.\n"
    "Last 1 line(s):\n"
    "[Error]: Layer 'GUARD_RING_MK' is not used. wafers.space requires a seal "
    "ring (guard ring) around the die.\n"
)


def _rundir_from_cmd(cmd):
    """The HOST directory bound to the container's run mount, out of the argv."""
    for i, tok in enumerate(cmd):
        if tok == "-v" and i + 1 < len(cmd):
            spec = cmd[i + 1]
            if spec.endswith(":" + mod._CONTAINER_RUNDIR):
                return Path(spec[: -(len(mod._CONTAINER_RUNDIR) + 1)])
    raise AssertionError(f"no run-dir mount in {cmd!r}")


class FakeDocker:
    """A scripted stand-in for the pinned container.

    `steps_written` is how many numbered step directories the graded run leaves
    behind — i.e. how far the ladder got.  `progress_total` is the denominator
    the run prints for itself.  Both are settable independently so the tests can
    drive the disagreement paths, which are the ones that must degrade to
    NOT_DETERMINED instead of picking a number.
    """

    def __init__(self, *, image_present=True, stages=LADDER, run_rc=1,
                 steps_written=3, progress_total=16, error_log=REAL_REFUSAL,
                 pull_ok=True, run_stdout=None, write_run_root=True):
        self.image_present = image_present
        self.stages = stages
        self.run_rc = run_rc
        self.steps_written = steps_written
        self.progress_total = progress_total
        self.error_log = error_log
        self.pull_ok = pull_ok
        self.run_stdout = run_stdout
        self.write_run_root = write_run_root
        self.calls = []

    def __call__(self, cmd, timeout):
        self.calls.append(list(cmd))
        if cmd[1:3] == ["image", "inspect"]:
            return (0, "sha256:feedface\n", "") if self.image_present \
                else (1, "", "No such image")
        if cmd[1] == "pull":
            if self.pull_ok:
                self.image_present = True
                return 0, "", ""
            return 1, "", "pull failed"
        if "-c" in cmd:                     # the enumeration probe
            if self.stages is None:
                return 1, "", "boom"
            payload = json.dumps([{"id": i, "name": n} for i, n in self.stages])
            return 0, mod._STAGES_MARKER + payload + "\n", ""
        # The graded run.
        run_root = _rundir_from_cmd(cmd) / "runs" / mod.RUN_TAG
        if self.write_run_root:
            run_root.mkdir(parents=True, exist_ok=True)
            for n in range(1, self.steps_written + 1):
                slug = mod.step_dir_slug(self.stages[n - 1][0]) if self.stages \
                    else f"step{n}"
                (run_root / f"{n:02d}-{slug}").mkdir(exist_ok=True)
            if self.error_log:
                (run_root / "error.log").write_text(self.error_log)
        out = self.run_stdout
        if out is None:
            done = max(self.steps_written - 1, 0)
            out = (f"PrecheckFlow - Stage {self.steps_written} ---  "
                   f"{done}/{self.progress_total} 0:00:03\n")
        return self.run_rc, out, ""


@pytest.fixture()
def layout(tmp_path):
    p = tmp_path / "chip_top.gds"
    p.write_bytes(b"\x00\x06\x00\x02\x00\x07not-a-real-gds")
    return p


def _eval(layout, fake, tmp_path, **kw):
    kw.setdefault("rundir", tmp_path / "run")
    return mod.evaluate(layout=layout, runner=fake,
                        which=lambda _b: "/usr/bin/docker", **kw)


# --------------------------------------------------------------------------- #
# 1. The digest pin
# --------------------------------------------------------------------------- #
class TestDigestPin:
    def test_shipped_pin_is_a_digest_not_a_tag(self):
        assert mod.is_digest_pinned(mod.PINNED_IMAGE)
        assert "@sha256:" in mod.PINNED_IMAGE
        assert not mod.PINNED_IMAGE.endswith(":main")

    @pytest.mark.parametrize("ref", [
        "ghcr.io/wafer-space/gf180mcu-precheck:main",
        "ghcr.io/wafer-space/gf180mcu-precheck",
        "ghcr.io/wafer-space/gf180mcu-precheck:latest",
        "ghcr.io/wafer-space/gf180mcu-precheck@sha256:tooshort",
        "",
    ])
    def test_unpinned_reference_is_refused(self, ref, layout, tmp_path):
        fake = FakeDocker()
        rep = _eval(layout, fake, tmp_path, image=ref)
        assert rep.verdict == mod.BLOCKED
        assert rep.blocked_reason == mod.B_IMAGE_NOT_DIGEST_PINNED
        assert rep.passed is False
        # Refused BEFORE anything ran: an unreproducible verdict is not produced
        # at all, rather than produced and then disclaimed.
        assert fake.calls == []

    def test_no_escape_hatch_exists_for_an_unpinned_image(self):
        """A flag that turns the pin off would be a supported way to make the
        gate's verdict unreproducible, so there must not be one."""
        opts = _cli_option_strings(Path(mod.__file__).read_text())
        assert "--image" in opts          # the parser really was scanned
        for opt in opts:
            low = opt.lower()
            assert "unpinned" not in low
            assert not ("pin" in low and ("no" in low or "skip" in low
                                          or "ignore" in low or "allow" in low))


# --------------------------------------------------------------------------- #
# 2. No network, and no way to run fewer checks
# --------------------------------------------------------------------------- #
class TestRunIsHermeticAndComplete:
    def test_graded_run_is_always_network_none_and_pull_never(self, tmp_path):
        cmd = mod.build_run_command(mod.PINNED_IMAGE, tmp_path / "a.gds",
                                    tmp_path / "r", "", "FFFFFFFF", "1x1", False)
        assert "--network=none" in cmd
        assert "--pull=never" in cmd

    def test_no_step_selection_is_plumbed_through(self, tmp_path):
        """`--from` / `--to` / `--skip` would let a caller pass the gate by
        running fewer of the shuttle's checks, so they are not exposed."""
        cmd = mod.build_run_command(mod.PINNED_IMAGE, tmp_path / "a.gds",
                                    tmp_path / "r", "", "FFFFFFFF", "1x1", True)
        for flag in ("--from", "--to", "--skip", "--last-run",
                     "--with-initial-state"):
            assert flag not in cmd
        # Exact string constants, not substrings: `--to` is a substring of the
        # legitimate `--top`, and a substring test would have banned it.
        lits = {n.value for n in ast.walk(
                    ast.parse(func_src(Path(mod.__file__).read_text(),
                                       "build_run_command")))
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        assert "--input" in lits          # the function really was scanned
        assert lits.isdisjoint({"--from", "--to", "--skip", "--last-run",
                                "--with-initial-state"})

    def test_paths_are_argv_tokens_so_a_newline_cannot_split_them(self, tmp_path):
        """The plugin's own EDA image reports `getpass.getuser()` as
        `'1000\\ndesigner'`, so a tmp path really does contain a newline there.
        A composed shell string splits on it; separate argv tokens do not."""
        weird = tmp_path / "a\ndir"
        weird.mkdir()
        gds = weird / "chip_top.gds"
        gds.write_bytes(b"x")
        cmd = mod.build_run_command(mod.PINNED_IMAGE, gds, weird / "r",
                                    "", "FFFFFFFF", "1x1", False)
        assert not any(tok.startswith("bash") for tok in cmd)
        assert "-c" not in cmd
        assert any(str(gds.resolve()) in tok for tok in cmd)

    def test_enumeration_probe_is_also_offline(self):
        cmd = mod.build_enumerate_command(mod.PINNED_IMAGE, False)
        assert "--network=none" in cmd and "--pull=never" in cmd


# --------------------------------------------------------------------------- #
# 3. BLOCKED is its own state, and it FAILS
# --------------------------------------------------------------------------- #
class TestBlockedIsItsOwnStateAndFails:
    def test_docker_missing(self, layout, tmp_path):
        rep = mod.evaluate(layout=layout, runner=FakeDocker(),
                           rundir=tmp_path / "run", which=lambda _b: None)
        assert (rep.verdict, rep.blocked_reason, rep.passed) == \
            (mod.BLOCKED, mod.B_DOCKER_UNAVAILABLE, False)

    def test_image_absent(self, layout, tmp_path):
        rep = _eval(layout, FakeDocker(image_present=False), tmp_path)
        assert (rep.verdict, rep.blocked_reason, rep.passed) == \
            (mod.BLOCKED, mod.B_IMAGE_ABSENT, False)

    def test_image_absent_can_be_recovered_by_an_explicit_pull(self, layout,
                                                               tmp_path):
        fake = FakeDocker(image_present=False, run_rc=0, steps_written=16)
        rep = _eval(layout, fake, tmp_path, allow_pull=True)
        assert rep.verdict == mod.PASS
        assert ["docker", "pull"] == fake.calls[1][:2]

    def test_container_failed_to_start(self, layout, tmp_path):
        rep = _eval(layout, FakeDocker(run_rc=125, write_run_root=False),
                    tmp_path)
        assert (rep.verdict, rep.blocked_reason) == \
            (mod.BLOCKED, mod.B_CONTAINER_FAILED_TO_START)
        assert rep.passed is False

    def test_nonzero_exit_with_no_evidence_is_blocked_not_refused(self, layout,
                                                                  tmp_path):
        """The plugin's own EDA image exits 1 with `error: cannot determine
        user's home directory` before any ladder runs — the SAME exit code a
        real refusal uses.  Evidence, not the code alone, separates them."""
        rep = _eval(layout, FakeDocker(run_rc=1, write_run_root=False), tmp_path)
        assert (rep.verdict, rep.blocked_reason) == \
            (mod.BLOCKED, mod.B_NO_EVIDENCE)

    def test_zero_exit_with_no_evidence_is_blocked_never_pass(self, layout,
                                                              tmp_path):
        """The most dangerous fabricated pass this gate could emit."""
        rep = _eval(layout, FakeDocker(run_rc=0, write_run_root=False), tmp_path)
        assert rep.verdict == mod.BLOCKED
        assert rep.blocked_reason == mod.B_NO_EVIDENCE
        assert rep.passed is False

    def test_timeout_is_blocked_not_a_refusal_and_not_a_pass(self, layout,
                                                             tmp_path):
        rep = _eval(layout, FakeDocker(run_rc=mod._TIMEOUT_RC), tmp_path)
        assert (rep.verdict, rep.blocked_reason) == (mod.BLOCKED, mod.B_TIMEOUT)

    def test_a_stale_run_directory_is_refused(self, layout, tmp_path):
        stale = tmp_path / "run"
        (stale / "runs" / mod.RUN_TAG / "01-klayout-readlayout").mkdir(parents=True)
        rep = _eval(layout, FakeDocker(), tmp_path, rundir=stale)
        assert (rep.verdict, rep.blocked_reason) == \
            (mod.BLOCKED, mod.B_RUNDIR_NOT_FRESH)

    def test_missing_layout_is_blocked(self, tmp_path):
        rep = mod.evaluate(layout=tmp_path / "nope.gds", runner=FakeDocker(),
                           rundir=tmp_path / "run",
                           which=lambda _b: "/usr/bin/docker")
        assert (rep.verdict, rep.blocked_reason) == \
            (mod.BLOCKED, mod.B_LAYOUT_ABSENT)

    @pytest.mark.parametrize("kw", [
        {"image_present": False},
        {"run_rc": 0, "write_run_root": False},
        {"run_rc": 125, "write_run_root": False},
        {"run_rc": mod._TIMEOUT_RC},
    ])
    def test_no_blocked_state_ever_reads_as_no_refusals_found(self, kw, layout,
                                                              tmp_path):
        rep = _eval(layout, FakeDocker(**kw), tmp_path)
        assert rep.verdict == mod.BLOCKED
        assert rep.passed is False
        text = mod.report_to_text(rep)
        assert text.startswith("tapeout_readiness_check: BLOCKED")
        # The phrase may appear ONLY as the explicit disclaimer, never as a
        # finding. Both are counted, so a future edit that states it as a
        # finding fails here even though the disclaimer is still present.
        assert text.count("no refusals found") == 1
        assert text.count("NOT 'no refusals found'") == 1
        assert rep.blocked_reason and rep.blocked_reason != ""

    def test_every_blocked_reason_is_distinguishable(self):
        reasons = {v for k, v in vars(mod).items()
                   if k.startswith("B_") and isinstance(v, str)}
        assert len(reasons) >= 8
        assert len(reasons) == len([k for k in vars(mod) if k.startswith("B_")])


# --------------------------------------------------------------------------- #
# 4. The refusal, and the stage accounting
# --------------------------------------------------------------------------- #
class TestRefusalAccounting:
    def test_three_of_sixteen_names_the_thirteen_that_never_ran(self, layout,
                                                                tmp_path):
        rep = _eval(layout, FakeDocker(run_rc=1, steps_written=3), tmp_path)
        assert rep.verdict == mod.REFUSED
        assert rep.passed is False
        assert rep.stage_summary == "3 of 16"
        assert rep.stages_total == 16
        assert rep.stopped_at_index == 3
        assert rep.stopped_at_stage == "Check Slot Size"
        assert len(rep.stages_never_ran) == 13
        assert rep.stages_never_ran[0] == "Generate ID"
        assert rep.stages_never_ran[-1] == "Write the Layout"

    def test_the_refusal_text_is_verbatim(self, layout, tmp_path):
        rep = _eval(layout, FakeDocker(run_rc=1, steps_written=3), tmp_path)
        assert "GUARD_RING_MK" in rep.refusal_text
        assert rep.refusal_text == REAL_REFUSAL.strip()
        assert "GUARD_RING_MK" in mod.report_to_text(rep)

    def test_the_human_report_leads_with_the_un_run_stages(self, layout,
                                                           tmp_path):
        rep = _eval(layout, FakeDocker(run_rc=1, steps_written=3), tmp_path)
        text = mod.report_to_text(rep)
        assert "3 of 16" in text
        assert "NEVER RAN   : 13 stage(s)" in text
        assert "1 failure" not in text

    def test_a_finished_ladder_does_not_read_as_a_halt(self, layout, tmp_path):
        """A PASS has no stage it stopped at, and no stage it skipped."""
        rep = _eval(layout, FakeDocker(run_rc=0, steps_written=16,
                                       error_log=None), tmp_path)
        text = mod.report_to_text(rep)
        assert "stopped at" not in text
        assert "last stage  : stage 16 — Write the Layout" in text
        assert "NEVER RAN   : none — every stage of the ladder ran" in text
        # The refusing shape still says it stopped.
        ref = _eval(layout, FakeDocker(run_rc=1, steps_written=3),
                    tmp_path, rundir=tmp_path / "run2")
        assert "stopped at  : stage 3" in mod.report_to_text(ref)

    def test_the_cob_ladder_changes_the_denominator(self, layout, tmp_path):
        cob = LADDER[:3] + [("KLayout.CheckPadMask", "Check Pad Mask")] \
            + LADDER[3:]
        rep = _eval(layout, FakeDocker(stages=cob, run_rc=1, steps_written=4,
                                       progress_total=17), tmp_path, cob=True)
        assert rep.stage_summary == "4 of 17"
        assert rep.stopped_at_stage == "Check Pad Mask"
        assert len(rep.stages_never_ran) == 13


# --------------------------------------------------------------------------- #
# 5. PASS needs evidence
# --------------------------------------------------------------------------- #
class TestPassNeedsEvidence:
    def test_full_ladder_and_zero_exit_is_a_pass(self, layout, tmp_path):
        rep = _eval(layout, FakeDocker(run_rc=0, steps_written=16,
                                       error_log=None), tmp_path)
        assert rep.verdict == mod.PASS
        assert rep.passed is True
        assert rep.stage_summary == "16 of 16"
        assert rep.stages_never_ran == []

    def test_zero_exit_over_a_short_ladder_is_not_a_pass(self, layout, tmp_path):
        rep = _eval(layout, FakeDocker(run_rc=0, steps_written=3,
                                       error_log=None), tmp_path)
        assert rep.verdict == mod.BLOCKED
        assert rep.blocked_reason == mod.B_EVIDENCE_CONTRADICTS_EXIT
        assert rep.stage_summary == "3 of 16"

    def test_cli_exit_code_follows_the_verdict(self, layout, tmp_path,
                                               monkeypatch, capsys):
        seen = {}

        def fake_eval(**kw):
            return mod.ReadinessReport(
                layout=str(layout), layout_sha256="x", image=mod.PINNED_IMAGE,
                verdict=seen["v"])
        monkeypatch.setattr(mod, "evaluate", fake_eval)
        out = tmp_path / "v.json"
        for verdict, code in ((mod.PASS, 0), (mod.REFUSED, 1), (mod.BLOCKED, 1)):
            seen["v"] = verdict
            assert mod.main(["--layout", str(layout),
                             "--out-json", str(out)]) == code
            assert json.loads(out.read_text())["verdict"] == verdict
            capsys.readouterr()

    def test_emitted_by_is_read_not_hardcoded(self, layout, tmp_path):
        rep = _eval(layout, FakeDocker(run_rc=0, steps_written=16,
                                       error_log=None), tmp_path)
        assert rep.as_dict()["emitted_by"].startswith(mod.TOOL + " v")


# --------------------------------------------------------------------------- #
# 6. NOT DETERMINED beats a guess
# --------------------------------------------------------------------------- #
class TestNeverGuesses:
    def test_no_enumeration_means_names_are_not_determined(self, layout,
                                                           tmp_path):
        """The verdict must survive; only the NAMES are lost."""
        rep = _eval(layout, FakeDocker(stages=None, run_rc=1, steps_written=3),
                    tmp_path)
        assert rep.verdict == mod.REFUSED
        assert rep.stages_never_ran == mod.NOT_DETERMINED
        # The run still printed its own denominator, so "3 of 16" survives.
        assert rep.stage_summary == "3 of 16"
        assert rep.stages_total_source == "run-progress"

    def test_disagreeing_denominators_are_not_determined(self, layout, tmp_path):
        rep = _eval(layout, FakeDocker(run_rc=1, steps_written=3,
                                       progress_total=99), tmp_path)
        assert rep.stages_total == mod.NOT_DETERMINED
        assert rep.stage_summary == mod.NOT_DETERMINED
        assert any("disagree" in n for n in rep.notes)

    def test_an_enumeration_that_does_not_match_the_run_is_not_used(self, layout,
                                                                    tmp_path):
        other = [(f"Some.Step{i}", f"Step {i}") for i in range(1, 17)]
        fake = FakeDocker(run_rc=1, steps_written=3)
        fake.stages = LADDER            # written dirs follow the real ladder

        class Mismatch(FakeDocker):
            def __call__(self, cmd, timeout):
                if "-c" in cmd:
                    payload = json.dumps(
                        [{"id": i, "name": n} for i, n in other])
                    return 0, mod._STAGES_MARKER + payload + "\n", ""
                return FakeDocker.__call__(self, cmd, timeout)

        rep = _eval(layout, Mismatch(run_rc=1, steps_written=3), tmp_path)
        assert rep.stages_never_ran == mod.NOT_DETERMINED
        assert any("does not match" in n for n in rep.notes)

    def test_no_container_rule_literal_is_carried_in_the_program(self):
        """The gate wraps; it must not restate a single rule it wraps.

        Every literal below is one the container decides with — the seal-ring
        marker layer, the die/slot dimensions, the pad layer, the ID cell
        prefix, the forbidden top-metal layers. A copy of any of them here is
        this module quietly becoming our own bar again, which is the exact
        failure the gate exists to remove."""
        code = _code_only(Path(mod.__file__).read_text())
        for lit in ("GUARD_RING_MK", "3880", "5070", "3932", "5122",
                    "gf180mcu_ws_ip__", "Via5", "MetalTop", "167", "(37, 0)"):
            assert lit not in code, f"{lit!r} is the container's rule, not ours"

    def test_no_reportable_ladder_is_carried_in_the_program(self):
        """The step DISPLAY NAMES are what the report prints, so a copy of them
        would let the gate keep naming stages confidently after the container's
        ladder changed underneath it. Exactly one container step id may appear
        in code — the anchor handed to the container's own `Flow.Substitute` —
        and more than that would be a ladder."""
        code = _code_only(Path(mod.__file__).read_text())
        for name in ("Read the Layout", "Check Top-Level Name",
                     "Check Slot Size", "Generate ID", "Check Pad Mask",
                     "Density Check", "Write the Layout"):
            assert name not in code, f"{name!r} is the container's answer"
        ids = set(re.findall(r"(?:KLayout|Checker|Magic)\.\w+", code))
        assert len(ids) <= 2, f"a ladder is being carried here: {sorted(ids)}"

    def test_parse_rejects_junk_rather_than_inventing_a_ladder(self):
        assert mod.parse_enumerated_stages("") is None
        assert mod.parse_enumerated_stages(mod._STAGES_MARKER + "{{") is None
        assert mod.parse_enumerated_stages(mod._STAGES_MARKER + "[]") is None
        assert mod.parse_enumerated_stages(mod._STAGES_MARKER + '[1,2]') is None


# --------------------------------------------------------------------------- #
# 7. Reading a written verdict back (the ladder's consumption boundary)
# --------------------------------------------------------------------------- #
class TestReadVerdict:
    def test_round_trips_a_real_verdict(self, layout, tmp_path):
        rep = _eval(layout, FakeDocker(run_rc=1, steps_written=3), tmp_path)
        f = tmp_path / "v.json"
        f.write_text(json.dumps(rep.as_dict()))
        got = mod.read_verdict(f)
        assert got["verdict"] == mod.REFUSED
        assert got["stage_summary"] == "3 of 16"

    @pytest.mark.parametrize("body", [
        "not json at all", "[]", '{"verdict": "PASS_WITH_WAIVERS"}',
        '{"verdict": null}', "{}", '"PASS"',
    ])
    def test_anything_unreadable_is_blocked_never_a_pass(self, body, tmp_path):
        f = tmp_path / "v.json"
        f.write_text(body)
        got = mod.read_verdict(f)
        assert got["verdict"] == mod.BLOCKED
        assert got["blocked_reason"] == mod.B_MALFORMED_REPORT

    def test_a_missing_file_is_blocked_never_a_pass(self, tmp_path):
        got = mod.read_verdict(tmp_path / "nope.json")
        assert got["verdict"] == mod.BLOCKED
        assert got["blocked_reason"] == mod.B_MALFORMED_REPORT


# --------------------------------------------------------------------------- #
# 8. Wiring — the publish path can see it, and the retired pointer is replaced
# --------------------------------------------------------------------------- #
def _write_verdict(project_dir: Path, **kw):
    p = project_dir / "reports" / "phase3" / "tapeout_readiness.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"verdict": mod.REFUSED, "stage_summary": "3 of 16",
               "refusal_text": REAL_REFUSAL, "image": mod.PINNED_IMAGE}
    payload.update(kw)
    p.write_text(json.dumps(payload))
    return p


class TestWiredIntoThePublishPath:
    def test_the_release_ladder_carries_the_live_tier(self, tmp_path):
        import signoff_ladder_run as slr
        _write_verdict(tmp_path)
        rep = slr.run_ladder(tmp_path, mode="tapeout")
        ids = [t.tier_id for t in rep.tiers]
        assert "T_TAPEOUT_READY" in ids

    def test_the_diagnostic_ladder_does_not_claim_a_submission(self, tmp_path):
        """`triage`'s own docstring says nothing there claims a tapeout, so the
        submission gate belongs to the release ladder only."""
        import signoff_ladder_run as slr
        _write_verdict(tmp_path)
        rep = slr.run_ladder(tmp_path, mode="triage")
        assert "T_TAPEOUT_READY" not in [t.tier_id for t in rep.tiers]

    @pytest.mark.parametrize("verdict,expected", [
        (mod.PASS, "PASS"),
        (mod.REFUSED, "FAIL"),
        (mod.BLOCKED, "INCOMPLETE"),
    ])
    def test_verdict_mapping(self, verdict, expected, tmp_path):
        import signoff_ladder_run as slr
        _write_verdict(tmp_path, verdict=verdict,
                       blocked_reason=mod.B_IMAGE_ABSENT, blocked_detail="x")
        tier = slr.check_tier_tapeout_readiness(tmp_path)
        assert tier.verdict == expected

    def test_absent_verdict_is_not_run_never_a_pass(self, tmp_path):
        import signoff_ladder_run as slr
        tier = slr.check_tier_tapeout_readiness(tmp_path)
        assert tier.verdict == "NOT_RUN"
        assert tier.release_gating is True

    def test_a_refusal_stops_the_release(self, tmp_path):
        import signoff_ladder_run as slr
        _write_verdict(tmp_path, verdict=mod.REFUSED)
        rep = slr.run_ladder(tmp_path, mode="tapeout")
        assert rep.overall_verdict == "FAIL"
        assert rep.released is False

    def test_a_blocked_verdict_does_not_release_and_is_not_a_finding(self,
                                                                    tmp_path):
        import signoff_ladder_run as slr
        _write_verdict(tmp_path, verdict=mod.BLOCKED,
                       blocked_reason=mod.B_IMAGE_ABSENT,
                       blocked_detail="image not present")
        rep = slr.run_ladder(tmp_path, mode="tapeout")
        assert rep.released is False
        tier = [t for t in rep.tiers if t.tier_id == "T_TAPEOUT_READY"][0]
        assert "NOT a finding of no refusals" in tier.notes

    def test_the_retired_shuttle_is_no_longer_the_pointer(self):
        """#1744's ask: the dead-shuttle pointer is REPLACED, and the retired
        one is marked rather than deleted."""
        import tapeout_checklist_gen as tcg
        gates = {row[3] for row in tcg._CHECKLIST_ITEMS}
        assert "tapeout_readiness_check" in gates
        assert "mpw_precheck_result_gate" in gates        # kept, not deleted
        assert "RETIRED" in tcg._GATE_NOTES["mpw_precheck_result_gate"]
        assert "tapeout_readiness_check" in tcg._GATE_NOTES
        # The live row is a blocker; a counterparty's refusal outranks an
        # inventory row's severity.
        live = [r for r in tcg._CHECKLIST_ITEMS
                if r[3] == "tapeout_readiness_check"][0]
        assert live[2] == "blocker"

    def test_the_retired_driver_says_so(self):
        import mpw_precheck_driver as mpd
        assert "RETIRED" in (mpd.__doc__ or "")
        assert "tapeout_readiness_check" in (mpd.__doc__ or "")
