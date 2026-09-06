#!/usr/bin/env python3
"""A tool is absent only where you looked — and the flow looks in two places.

MEASURED, on a completed sign-off run (`phase3` verdict FAIL, 20 of its 21
step-3 steps green):

    ENV_UNAVAILABLE  digital_hardmacro_gen
    [SKIPPED_NO_CAPABILITY] magic is not on PATH in this environment;
                            produced spm.gds, spm.v, spm.lib

while THE SAME RUN's provenance ledger carries

    {"tool": "magic", "version": "8.3.681", "exit_code": 0, ...}

Both statements were true of the environment each was made in. The runner
executes on the HOST and dispatches every EDA tool into the EDA CONTAINER, so
`shutil.which("magic")` interrogated the one environment the tools are known
not to be in, and the answer was published as a capability gap. The PDK is on
the same side as the tools — `/foss/pdks` is not on the host filesystem — so
the technology lookup and the launch were the same error twice more.

WHAT THESE TESTS PIN, and they are two opposite directions:

  1. When magic IS reachable, it is REACHED — here first, and otherwise in
     the container the flow dispatches into, with the work files crossing
     with it.
  2. When magic is reachable NOWHERE, the capability gap is STILL reported.
     A probe that has stopped being able to say no is worse than one that
     says no wrongly: it converts every absent tool into a silent pass.

chip/PDK-AGNOSTIC: no design or PDK name is required by any assertion below.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
sys.path.insert(0, str(_PROGRAMS))

import digital_hardmacro_gen as mod  # noqa: E402
from test_digital_hardmacro_gen import DEF_OK, make_project  # noqa: E402

PROG = _PROGRAMS / "digital_hardmacro_gen.py"


# ── 1. where it looks ──────────────────────────────────────────────────────

def test_this_environment_answers_first_and_costs_no_container_call(monkeypatch):
    """Inside the image there is magic on PATH and no docker client at all.

    Host first is not a preference: it is what makes ONE program correct in
    both environments the flow runs in.
    """
    monkeypatch.setattr(mod.shutil, "which",
                        lambda n: "/foss/tools/bin/magic" if n == "magic"
                        else None)

    def _no_subprocess(*_a, **_k):                       # pragma: no cover
        raise AssertionError("magic is on PATH here and a container was "
                             "still asked; the probe costs a subprocess it "
                             "does not need")
    monkeypatch.setattr(mod, "_sh", _no_subprocess)

    site = mod.find_magic_site("some_container")
    assert site is not None and site.in_container is False
    assert site.where == "this environment"


def test_the_container_is_asked_when_this_environment_has_no_magic(monkeypatch):
    """THE DEFECT, pinned. The probe must cross the boundary the tools are on."""
    monkeypatch.setattr(mod.shutil, "which",
                        lambda n: "/usr/bin/docker" if n == "docker" else None)
    asked = {}

    def fake_run_in_container(container, cmd, deadline_s=120, **_k):
        asked["container"] = container
        asked["cmd"] = cmd
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(mod._container_exec, "run_in_container",
                        fake_run_in_container)

    site = mod.find_magic_site("eda_ctr")
    assert site is not None, (
        "magic is absent from this environment and present in the container, "
        "and the probe reported the tool absent — the exact false negative "
        "this file exists for")
    assert site.in_container and site.container == "eda_ctr"
    assert asked["container"] == "eda_ctr"
    assert "command -v magic" in asked["cmd"]


def test_the_technology_is_listed_where_the_tool_will_read_it(monkeypatch):
    """`/foss/pdks` is not on the host either, so the glob crossed too.

    AND THE LISTING IGNORES THE IMAGE'S LOGIN BANNER. The image prints
    `[INFO] Final PATH variable: ...` on every login shell, ahead of the
    command's own output; counting those lines as candidates would hand
    `choose_magicrc` a first entry that is not a technology file at all.
    """
    site = mod.MagicSite("eda_ctr")
    listed = []

    def fake_run_in_container(container, cmd, deadline_s=120, **_k):
        listed.append(cmd)
        out = ("[INFO] Final PATH variable: /headless/.local/bin\n"
               "/pdks/somepdk/libs.tech/magic/somepdk.magicrc\n"
               if "/*/libs.tech" in cmd else "[INFO] Final PATH variable: /x\n")
        return subprocess.CompletedProcess([], 0, out, "")

    monkeypatch.setattr(mod._container_exec, "run_in_container",
                        fake_run_in_container)
    got = site.magicrc("/pdks")
    assert got == "/pdks/somepdk/libs.tech/magic/somepdk.magicrc", got
    assert any("/pdks/libs.tech/magic/" in c for c in listed), listed


def test_the_choice_between_technologies_is_the_same_rule_on_both_sides():
    """One rule, two filesystems — two copies would be free to disagree."""
    assert mod.choose_magicrc(["/p/libs.tech/magic/a.magicrc"],
                              ["/other.magicrc"]) \
        == "/p/libs.tech/magic/a.magicrc"
    assert mod.choose_magicrc([], ["/only/one.magicrc"]) == "/only/one.magicrc"
    # more than one, and nothing here says which the design is on
    assert mod.choose_magicrc([], ["/a.magicrc", "/z.magicrc"]) is None


def test_pdk_and_pdk_root_are_read_off_the_technology_that_was_chosen():
    """MEASURED: PDK_ROOT set to the PDK DIRECTORY makes magic exit 0 and
    write no LEF (`Could not find file '<root>/<pdk>/<pdk>/…tech'`), because
    the system magicrc composes `$PDK_ROOT/$PDK/…` and reads both together.
    """
    env = mod.magic_env_for("/foss/pdks/somepdk/libs.tech/magic/x.magicrc",
                            "/foss/pdks/somepdk")
    assert env == {"PDK": "somepdk", "PDK_ROOT": "/foss/pdks"}


def test_the_lef_is_written_in_the_container_and_comes_back(tmp_path, monkeypatch):
    """The whole crossing, end to end: probe, listing, staging, launch, fetch."""
    ctr_root = tmp_path / "container_fs"
    (ctr_root / "work").mkdir(parents=True)
    written = {}

    def _local(p: str) -> str:
        return str(ctr_root / "work") if p == "/ctr/work" else p.replace(
            "/ctr/work", str(ctr_root / "work"))

    def fake_sh(argv, timeout=900):
        argv = [str(a) for a in argv]
        if argv[:2] == ["docker", "exec"] and argv[3] == "mktemp":
            return 0, "/ctr/work\n", ""
        if argv[:2] == ["docker", "exec"] and argv[3] == "rm":
            return 0, "", ""
        if argv[:2] == ["docker", "cp"]:
            src, dst = argv[2].split(":")[-1], argv[3].split(":")[-1]
            Path(_local(dst)).write_bytes(Path(_local(src)).read_bytes())
            return 0, "", ""
        raise AssertionError(f"unexpected client call: {argv}")

    def fake_run_in_container(container, cmd, deadline_s=120, **_k):
        if "command -v magic" in cmd:
            return subprocess.CompletedProcess([], 0, "", "")
        if cmd.startswith("ls -1d"):
            out = ("/pdks/p/libs.tech/magic/p.magicrc\n"
                   if "/*/libs.tech" in cmd else "")
            return subprocess.CompletedProcess([], 0, out, "")
        if cmd.startswith("magic --version"):
            return subprocess.CompletedProcess([], 0, "8.3.681\n", "")
        written["cmd"] = cmd
        # the tool writes its LEF into ITS OWN work directory
        (ctr_root / "work" / "macro_a.lef").write_text(
            "MACRO macro_a\n  PIN clk\n    DIRECTION INPUT ;\n  END clk\n"
            "END macro_a\n")
        return subprocess.CompletedProcess([], 0, "DIGITAL_LEF_WRITE_DONE", "")

    monkeypatch.setattr(mod.shutil, "which",
                        lambda n: "/usr/bin/docker" if n == "docker" else None)
    monkeypatch.setattr(mod, "_sh", fake_sh)
    monkeypatch.setattr(mod._container_exec, "run_in_container",
                        fake_run_in_container)

    gds = tmp_path / "in.gds"
    gds.write_bytes(b"\x00\x06\x00\x02\x00\x07")
    dfp = tmp_path / "in.def"
    dfp.write_text(DEF_OK)
    out_lef = tmp_path / "kit" / "macro_a.lef"

    ok, why = mod.write_lef_with_magic("macro_a", gds, dfp, out_lef, "/pdks",
                                       False, False, container="eda_ctr")
    assert ok, why
    assert out_lef.is_file() and "PIN clk" in out_lef.read_text()
    # the launch used the technology found IN THE CONTAINER, and exported the
    # two variables the system magicrc reads together
    assert "-rcfile /pdks/p/libs.tech/magic/p.magicrc" in written["cmd"]
    assert "PDK=p" in written["cmd"] and "PDK_ROOT=/pdks" in written["cmd"]
    # and the inputs crossed with it, rather than being assumed visible
    assert "/ctr/work/macro_a.gds" in written["cmd"] or (
        ctr_root / "work" / "macro_a.gds").is_file()


# ── 2. THE CONTROL: it must still be able to say no ────────────────────────

def test_a_container_that_has_no_magic_is_still_the_capability_gap(monkeypatch):
    monkeypatch.setattr(mod.shutil, "which",
                        lambda n: "/usr/bin/docker" if n == "docker" else None)
    monkeypatch.setattr(
        mod._container_exec, "run_in_container",
        lambda *_a, **_k: subprocess.CompletedProcess([], 1, "", ""))
    assert mod.find_magic_site("eda_ctr") is None
    why = mod.magic_absent_reason("eda_ctr")
    assert "not on PATH" in why and "eda_ctr" in why


def test_no_client_to_cross_with_is_still_the_capability_gap(monkeypatch):
    monkeypatch.setattr(mod.shutil, "which", lambda _n: None)

    def _no_subprocess(*_a, **_k):                       # pragma: no cover
        raise AssertionError("there is no docker client here; nothing should "
                             "have been launched")
    monkeypatch.setattr(mod, "_sh", _no_subprocess)
    assert mod.find_magic_site("eda_ctr") is None
    assert "docker client" in mod.magic_absent_reason("eda_ctr")


def test_a_path_without_magic_still_refuses_end_to_end(tmp_path):
    """THE CONTROL, through the CLI the runner actually invokes.

    An environment probe that has stopped being able to report an absent
    tool is worse than the false negative it replaced, so this arm runs the
    real program with a PATH that carries neither magic nor a docker client
    and demands rc 2, the stated gap, and NO staged abstract.

    THE PATH IS CONSTRUCTED, NOT ASSUMED. This arm used to name the host's own
    "/usr/bin:/bin" and then ASSERT that neither tool was on it. That is a
    statement about the host, not about the program: the distribution package
    of the docker CLI installs it as "/usr/bin/docker", so on every host that
    has one the premise assertion is what goes red, and the control this arm
    exists to be never runs at all. An EMPTY directory carries neither tool on
    every host, so the two premise assertions below now guard a fact this test
    MADE true instead of one it hoped the host would supply.
    """
    project = make_project(tmp_path)
    out = tmp_path / "gen.json"
    empty_bin = tmp_path / "no_tools_bin"
    empty_bin.mkdir()
    env = dict(os.environ)
    env["PATH"] = str(empty_bin)
    assert shutil.which("magic", path=env["PATH"]) is None
    assert shutil.which("docker", path=env["PATH"]) is None
    cp = subprocess.run(
        [sys.executable, str(PROG), str(project), "--json", str(out),
         "--pdk-root", str(tmp_path / "no_pdk"), "--container", "eda_ctr"],
        capture_output=True, text=True, env=env)
    assert cp.returncode == 2, cp.stdout + cp.stderr
    rec = json.loads(out.read_text())
    assert rec["status"] == "SKIPPED_NO_CAPABILITY"
    assert "magic" in rec["reason"]
    assert "macro_a.lef" not in rec["produced"]
    assert not (project / "phase3/stage4/hardmacro/macro_a.lef").exists()
    # and the three views it CAN produce without magic are still produced
    assert {"macro_a.gds", "macro_a.v", "macro_a.lib"} <= set(rec["produced"])


# ── the tool itself, where this suite runs ─────────────────────────────────

@pytest.mark.skipif(shutil.which("magic") is None,
                    reason="no magic in this environment to answer for itself")
def test_a_reachable_magic_answers_with_its_own_banner():
    """Not a mock: the resolver's answer is checked against the real tool."""
    site = mod.find_magic_site("host")
    assert site is not None and site.in_container is False
    assert site.magic_version().strip(), (
        "the site resolved but the tool it resolved to said nothing")


# ── the runner half: it must hand over the container ───────────────────────

def _runner():
    sys.path.insert(0, str(_PROGRAMS))
    import phase3_one_shot_runner as r
    return r


def test_the_runner_hands_the_producer_the_container_the_tools_are_in(
        tmp_path, monkeypatch):
    """This step is a plain host subprocess between steps that are dispatched.

    Without the container name the producer probes the one environment magic
    is known not to be in — which is how a run whose own provenance carries a
    successful magic invocation reported magic absent.
    """
    r = _runner()
    seen = {}

    def fake_run(cmd, **_kw):
        seen["cmd"] = [str(c) for c in cmd]
        return subprocess.CompletedProcess(cmd, 0, "ok\n", "")

    # RECORD AT EVERY RUN-SHAPED SEAM THE STEP MAY DISPATCH THROUGH.
    #
    # v1.17.70 (measured 2026-09-07 on 8HD-4) moved this step's launch onto
    # `_run_producer`, which dispatches through `_progress_run.run` — progress
    # supervision instead of a wall clock — and `_progress_run` spawns with
    # `subprocess.Popen`. Stubbing `subprocess.run` alone therefore recorded
    # nothing at all, and this test failed with a bare `KeyError: 'cmd'`: a
    # message about the RECORDER that read like a message about the argv.
    #
    # The property under test is that the step hands the producer `--container
    # <name>`. That is true or false regardless of which helper carries the
    # argv there, so every seam is watched at once and the assertion below
    # names them when nothing arrives.
    _seams = (("_progress_run.run", r._pr, "run"),
              ("subprocess.run", r.subprocess, "run"))
    for _name, _owner, _attr in _seams:
        monkeypatch.setattr(_owner, _attr, fake_run)
    r.step_digital_hardmacro_gen(tmp_path, None, "eda_ctr")
    # REFUSE BY NAME, never `seen.get("cmd", [])`: an absent recording is not
    # an empty argv, and defaulting it would turn "I never saw the launch"
    # into "the launch carried no --container" — a different, false finding.
    assert "cmd" in seen, (
        "the step launched nothing through any watched seam ("
        + ", ".join(n for n, _o, _a in _seams) + "), so this test observed "
        "NO argv. That is not evidence that --container was omitted; it means "
        "the recorder and the step no longer meet. Find the seam the step "
        "dispatches through and add it above before reading this as a defect "
        "in step_digital_hardmacro_gen.")
    assert "--container" in seen["cmd"], seen["cmd"]
    assert seen["cmd"][seen["cmd"].index("--container") + 1] == "eda_ctr"


def test_the_pdk_directory_is_confirmed_where_the_pdk_is_installed(
        tmp_path, monkeypatch):
    """`$PDK_ROOT` names a CONTAINER path, so the host answer is None on
    every real run — and the producer then fell back to a `$PDK_ROOT` it
    could not see either. The tech LEF the run is already driving OpenROAD
    with names the same directory, and the container confirms it holds the
    technology."""
    r = _runner()
    monkeypatch.delenv("PDK_ROOT", raising=False)
    pdk = type("P", (), {"name": "somepdk",
                         "tech_lef": "/foss/pdks/somepdk/libs.ref/x/y.tlef"})()
    asked = {}

    def fake_exec(container, cmd, timeout=1800, **_k):
        asked["container"], asked["cmd"] = container, cmd
        return 0, "", ""

    monkeypatch.setattr(r, "_docker_exec", fake_exec)
    got = r._hardmacro_pdk_dir(pdk, "eda_ctr")
    assert got == "/foss/pdks/somepdk", got
    assert asked["container"] == "eda_ctr"
    assert "/foss/pdks/somepdk/libs.tech/magic" in asked["cmd"]

    # AND IT STILL DEGRADES TO A REFUSAL: a container that does not hold the
    # technology resolves nothing, rather than a directory nobody confirmed.
    monkeypatch.setattr(r, "_docker_exec",
                        lambda *_a, **_k: (1, "", "no such directory"))
    assert r._hardmacro_pdk_dir(pdk, "eda_ctr") is None
    # and with no container to ask, nothing is invented either
    assert r._hardmacro_pdk_dir(pdk, "") is None


# ── the whole crossing, end to end, through the CLI the runner invokes ────

_DOCKER_SHIM = """#!/bin/bash
# A stand-in docker CLI. `exec` and `cp` act on THIS filesystem, so the whole
# container leg — probe, technology listing, staging, launch, fetch — runs on
# a machine with no docker daemon. $REAL_PATH plays "the PATH inside the
# container", and is the only place the tool can be found. $REAL_HOME is the
# container's home, not the caller's: `bash -lc` must read the far side's login
# environment rather than inheriting whichever profile launched this test.
case "$1" in
  exec) shift; shift; exec env HOME="$REAL_HOME" PATH="$REAL_PATH" "$@" ;;
  cp)   shift; s="${1#*:}"; d="${2#*:}"; exec cp "$s" "$d" ;;
  *)    echo "stand-in docker: unsupported: $*" >&2; exit 127 ;;
esac
"""

#: A stand-in magic. THE TOOL IS NOT THE SUBJECT HERE — where it is looked for
#: is — and a real magic on a synthetic fixture GDS was measured SEGFAULTING
#: intermittently ("Unknown layer/datatype in boundary" then signal 11), which
#: would make this arm's colour depend on the tool's mood rather than on the
#: behaviour it pins. It writes its LEF to the path the recipe's own tcl names,
#: so the tcl, the staging and the fetch are all still exercised for real.
#: A stand-in `magic` that MIRRORS THE DEF IT WAS HANDED, rather than a fixed
#: one-pin string.
#:
#: MEASURED on live main v1.16.32 (bcedcdf25d9c), 2026-09-02: this stub emitted
#: `PIN clk` and nothing else, so the abstract it wrote dropped BOTH supply
#: ports of the fixture DEF. That is exactly the tool behaviour #1991 taught
#: this producer to refuse, so the arm below asked for rc 0 and got
#:
#:     [REFUSED_NOT_INTEGRABLE] ... expected {'vpwr': 'POWER', 'vgnd':
#:     'GROUND'}; macro_a.lef has {}
#:
#: The refusal was CORRECT and the double was stale: #1991 changed what a
#: deliverable abstract is and this arm's magic was never taught it. The arm's
#: subject is the container BOUNDARY — that magic one `docker cp` away still
#: writes the abstract — and a stub that also drops the rails tests the
#: boundary through a second, unrelated failure.
#:
#: So the stub now reads the `def read` line out of the very TCL the producer
#: emitted and reflects those PINS back, the same contract
#: `test_issue1991_hardmacro_supply_pins._lef_from_def` holds on the other
#: side. A magic that drops a rail is still a case this suite owns — it is
#: `test_magic_success_that_drops_one_supply_is_not_integrable`, where the
#: drop is the subject rather than an accident of the fixture.
_MAGIC_STUB = """#!/bin/bash
# NOT ONE ESCAPE SEQUENCE IN THIS SCRIPT, AND THE REASON IS MEASURED. This
# string is unescaped TWICE on its way to bash -- once by the Python source
# that holds it, once more by nothing at all -- so a `\\n` written here with one
# backslash too few arrives as a real newline and awk answers
# `awk: line 8: runaway string constant`, on stderr nobody reads, and the LEF
# comes out with no PIN in it. `print` supplies its own newline and `echo`
# needs none, so there is nothing here to get the escaping wrong on.
if [ "$1" = "--version" ]; then echo "0.0.0-stand-in"; exit 0; fi
tcl="${@: -1}"
out=$(grep -oE 'lef write [^ ]+' "$tcl" | head -1 | awk '{print $3}')
[ -n "$out" ] || { echo "no lef write line in $tcl" >&2; exit 1; }
def=$(grep -oE 'def read [^ ]+' "$tcl" | head -1 | awk '{print $3}')
[ -n "$def" ] || { echo "no def read line in $tcl" >&2; exit 1; }
top=$(grep -oE '^load [^ ]+' "$tcl" | head -1 | awk '{print $2}')
[ -n "$top" ] || { echo "no load line in $tcl" >&2; exit 1; }
{
  echo "MACRO $top"
  echo "  SIZE 100 BY 50 ;"
  awk '/^END PINS/{p=0}
       p && /^[[:space:]]*- / {
         name=$2; use="SIGNAL"; dir="INOUT";
         for (i=1;i<=NF;i++) {
           if ($i=="USE") use=$(i+1);
           if ($i=="DIRECTION") dir=$(i+1);
         }
         print "  PIN " name;
         print "    DIRECTION " dir " ;";
         print "    USE " use " ;";
         print "    PORT";
         print "      LAYER met2 ;";
         print "      RECT 1 1 2 2 ;";
         print "    END";
         print "  END " name;
       }
       /^PINS /{p=1}' "$def"
  echo "END $top"
  echo "END LIBRARY"
} > "$out"
echo "DIGITAL_LEF_WRITE_DONE $top"
"""


def _stand_in_environment(tmp_path):
    """(env, pdk_dir): magic is reachable ONLY on the far side of a docker cp."""
    shim = tmp_path / "here"
    shim.mkdir()
    (shim / "docker").write_text(_DOCKER_SHIM)
    (shim / "docker").chmod(0o755)
    there = tmp_path / "there"
    there.mkdir()
    (there / "magic").write_text(_MAGIC_STUB)
    (there / "magic").chmod(0o755)
    far_home = tmp_path / "far_home"
    far_home.mkdir()
    (far_home / ".bash_profile").write_text(
        '# The stand-in container owns its login environment.\n'
        'export PATH="$REAL_PATH"\n')
    pdk = tmp_path / "pdks" / "somepdk"
    (pdk / "libs.tech" / "magic").mkdir(parents=True)
    (pdk / "libs.tech" / "magic" / "somepdk.magicrc").write_text("# tech\n")

    env = dict(os.environ)
    env["REAL_HOME"] = str(far_home)
    env["REAL_PATH"] = f"{there}:/usr/bin:/bin"
    env["PATH"] = f"{shim}:/usr/bin:/bin"
    # named through the environment, so the argv is one the UNFIXED program
    # also accepts and this arm's red is a behaviour, not an unknown flag
    env["VIBEIC_EDA_CONTAINER"] = "eda_ctr"
    return env, pdk


def test_magic_reachable_only_across_the_boundary_still_writes_the_abstract(
        tmp_path):
    """THE MEASURED DEFECT, end to end, through the CLI the runner invokes.

    The producer's own process cannot see magic — exactly the host's
    situation — while magic and the PDK are one `docker exec` away. The
    unfixed program answers this with `[SKIPPED_NO_CAPABILITY] magic is not
    on PATH in this environment` and a kit with no abstract in it.
    """
    env, pdk = _stand_in_environment(tmp_path)
    assert shutil.which("magic", path=env["PATH"]) is None
    project = make_project(tmp_path)
    out = tmp_path / "gen.json"

    cp = subprocess.run(
        [sys.executable, str(PROG), str(project), "--json", str(out),
         "--pdk-root", str(pdk)],
        capture_output=True, text=True, env=env)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    rec = json.loads(out.read_text())
    assert rec["status"] == "PRODUCED", rec
    assert "macro_a.lef" in rec["produced"], rec
    # the record says WHICH environment answered, so the next reader can
    # compare it against the provenance ledger instead of guessing
    assert rec["lef_policy"]["magic_site"] == "container 'eda_ctr'", rec
    lef = project / "phase3/stage4/hardmacro/macro_a.lef"
    assert "PIN clk" in lef.read_text(), (
        "an abstract with no pin is an outline with nothing to connect to")


def test_the_same_crossing_with_nothing_on_the_far_side_still_says_no(tmp_path):
    """THE CONTROL FOR THE ARM ABOVE, one variable changed.

    Same stand-in client, same argv, same everything — except the far side
    has no magic either. The step must report the gap, not inherit the
    previous arm's success.
    """
    env, pdk = _stand_in_environment(tmp_path)
    (tmp_path / "there" / "magic").unlink()
    project = make_project(tmp_path)
    out = tmp_path / "gen.json"

    cp = subprocess.run(
        [sys.executable, str(PROG), str(project), "--json", str(out),
         "--pdk-root", str(pdk)],
        capture_output=True, text=True, env=env)
    assert cp.returncode == 2, cp.stdout + cp.stderr
    rec = json.loads(out.read_text())
    assert rec["status"] == "SKIPPED_NO_CAPABILITY"
    assert "eda_ctr" in rec["reason"], rec["reason"]
    assert not (project / "phase3/stage4/hardmacro/macro_a.lef").exists()


def test_a_missing_far_side_does_not_inherit_the_callers_login_magic(tmp_path):
    """A caller profile is not part of the stand-in container's filesystem.

    `_container_exec` launches `timeout ... bash -lc ...`. A double that only
    sets PATH before that login shell can still source the caller's profile and
    replace the declared far-side PATH. Planting a poison Magic in that profile
    makes the leak observable: with no Magic on the far side, the binary must
    never be executed and the result must remain the named capability gap.
    """
    env, pdk = _stand_in_environment(tmp_path)
    (tmp_path / "there" / "magic").unlink()

    poison_called = tmp_path / "caller_magic_was_executed"
    caller_bin = tmp_path / "caller_bin"
    caller_bin.mkdir()
    (caller_bin / "magic").write_text(
        "#!/bin/bash\n"
        f"touch {shlex.quote(str(poison_called))}\n"
        'if [ "$1" = "--version" ]; then echo "caller-magic"; fi\n'
        "exit 0\n")
    (caller_bin / "magic").chmod(0o755)
    caller_home = tmp_path / "caller_home"
    caller_home.mkdir()
    (caller_home / ".bash_profile").write_text(
        f"export PATH={shlex.quote(str(caller_bin))}:/usr/bin:/bin\n")
    env["HOME"] = str(caller_home)

    project = make_project(tmp_path)
    out = tmp_path / "gen.json"
    cp = subprocess.run(
        [sys.executable, str(PROG), str(project), "--json", str(out),
         "--pdk-root", str(pdk)],
        capture_output=True, text=True, env=env)

    assert not poison_called.exists(), (
        "the stand-in container inherited and executed the caller's Magic")
    assert cp.returncode == 2, cp.stdout + cp.stderr
    rec = json.loads(out.read_text())
    assert rec["status"] == "SKIPPED_NO_CAPABILITY"
    assert "eda_ctr" in rec["reason"], rec["reason"]
    assert not (project / "phase3/stage4/hardmacro/macro_a.lef").exists()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
