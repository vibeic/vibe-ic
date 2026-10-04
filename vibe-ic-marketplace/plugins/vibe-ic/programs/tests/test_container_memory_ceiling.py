#!/usr/bin/env python3
"""Every `docker run` this plugin issues must carry a memory ceiling.

MEASURED 2026-08-19 across a seven-machine fleet: 45 EDA containers were
running with `HostConfig.Memory == 0`. A container with no cgroup limit does
not share the host's memory — it IS the host's memory — and `ulimit -v` inside
our image is `unlimited`, so a tool never gets an allocation failure it could
report. On two of those machines a yosys took the whole box: the kernel's OOM
report shows two siblings at 54 GB apiece, then 109 GB for the survivor once
its twin was killed and the room freed. What actually died was chrome and Xorg
— the desktop session — because the OOM killer picks by oom_score_adj, not by
who caused the pressure.

Proven on the shipped image before any of this was written:

    --memory 512m   -> killed at 448 MiB, host `available` unchanged
    no --memory     -> the identical allocation reached 4096 MiB and exited 0

so the ceiling is what makes the difference, not the allocator.

The load-bearing test in this file is `test_no_docker_run_escapes_the_ceiling`.
The others check the arithmetic; that one checks that the arithmetic is
actually reachable from every place a container is created, which is the half
that decays — a new `docker run` added six months from now inherits nothing
unless something refuses it.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]
sys.path.insert(0, str(_PROGRAMS))

import _docker_memory as dm  # noqa: E402
import _watchdog  # noqa: E402

_GIB = 1024 ** 3


def _supervised(cmd, **kw):
    """`subprocess.run(cmd, capture_output=True, text=True, check=False)` with
    the wall-clock budget REPLACED by forward-progress supervision.

    Every call site below used to carry `timeout=60` / `timeout=120`. Neither
    number is a property of `_docker_memory.py` or of an import probe — both are
    guesses about a HOST, and when the guess is wrong on a loaded machine the
    `TimeoutExpired` propagates out of the test and is recorded as the SUBJECT
    being broken. That verdict is manufactured by the machine, not measured on
    the program. `run_host_supervised` bounds NO FORWARD PROGRESS instead (CPU +
    I/O summed over the child's /proc tree, plus the growth of its captured
    output), so a child that is merely slow finishes however long that
    legitimately takes, while one that is genuinely hung is still killed — and
    arrives as rc `_watchdog.RC_STALLED` with WATCHDOG_STALLED on stderr, a code
    none of these subjects can produce itself, so a hang can never be misread as
    an ordinary non-zero exit."""
    res = _watchdog.run_host_supervised(cmd, **kw)
    return _watchdog.completed_process(cmd, res)


# ── the ceiling itself ──────────────────────────────────────────────────────

def test_the_default_is_a_fraction_of_physical_memory():
    total = dm.physical_memory_bytes()
    assert total and total > 0, "this platform reports no physical memory"
    flags = dm.docker_memory_flags({"VIBEIC_DOCKER_MEMORY_FRACTION": "25"})
    assert flags[0] == "--memory"
    assert int(flags[1]) == total * 25 // 100


def test_memory_swap_is_always_pinned_to_memory():
    """`--memory` alone still lets the container reach the host's swap, which
    is the half of the incident that froze the machine before it crashed."""
    for env in ({}, {"VIBEIC_DOCKER_MEMORY": "48g"},
                {"VIBEIC_DOCKER_MEMORY_FRACTION": "10"}):
        flags = dm.docker_memory_flags(env)
        assert flags[0::2] == ["--memory", "--memory-swap"], env
        assert flags[1] == flags[3], env


def test_a_derived_ceiling_is_a_plain_byte_count():
    """`docker run --memory 1.34974e+11` is a hard error, not a big number.

    The shell version of this ceiling shipped with `awk '{print $2 * 1024}'`,
    which printed 134973464576 on one host and `1.34974e+11` on five others —
    awk switches to OFMT above an implementation-dependent magnitude — and all
    five silently ran unbounded. Nothing here goes through a number formatter.
    """
    flags = dm.docker_memory_flags({})
    assert re.fullmatch(r"[0-9]+", flags[1]), flags


def test_an_explicit_ceiling_is_passed_through_verbatim():
    assert dm.docker_memory_flags({"VIBEIC_DOCKER_MEMORY": "48g"}) == \
        ["--memory", "48g", "--memory-swap", "48g"]


def test_opting_out_emits_no_flag_at_all():
    """`--memory 0` is rejected by docker; opting out must emit nothing."""
    for value in ("0", "unlimited", "none", "OFF", " 0 "):
        assert dm.docker_memory_flags({"VIBEIC_DOCKER_MEMORY": value}) == [], value


def test_a_nonsense_fraction_falls_back_to_the_default_not_to_nothing():
    """A typo must not silently disable the ceiling."""
    for bad in ("", "0", "101", "seventy", "-5", "3.5"):
        flags = dm.docker_memory_flags({"VIBEIC_DOCKER_MEMORY_FRACTION": bad})
        assert flags, bad
        assert int(flags[1]) == dm.physical_memory_bytes() * dm.DEFAULT_FRACTION // 100


def test_the_ceiling_never_drops_below_the_floor_or_above_the_host(monkeypatch):
    monkeypatch.setattr(dm, "physical_memory_bytes", lambda: 1 * _GIB)
    # a 1 GiB host: the floor would exceed it, so the host total wins
    assert int(dm.docker_memory_flags({})[1]) == 1 * _GIB
    monkeypatch.setattr(dm, "physical_memory_bytes", lambda: 64 * _GIB)
    assert int(dm.docker_memory_flags({"VIBEIC_DOCKER_MEMORY_FRACTION": "1"})[1]) \
        == dm.FLOOR_BYTES


# ── the CLI the shell installer reads ───────────────────────────────────────

def _cli(*args, env=None):
    import os
    e = dict(os.environ)
    e.pop("VIBEIC_DOCKER_MEMORY", None)
    e.pop("VIBEIC_DOCKER_MEMORY_FRACTION", None)
    e.update(env or {})
    return _supervised([sys.executable, str(_PROGRAMS / "_docker_memory.py"), *args],
                       env=e)


def test_the_cli_prints_the_flags_one_per_line():
    r = _cli("--flags")
    assert r.returncode == 0, r.stderr
    lines = r.stdout.split()
    assert lines[0::2] == ["--memory", "--memory-swap"]
    assert lines[1] == lines[3]


def test_the_cli_says_nothing_when_opted_out():
    r = _cli("--flags", env={"VIBEIC_DOCKER_MEMORY": "0"})
    assert r.returncode == 0 and r.stdout.strip() == ""


def test_the_cli_refuses_rather_than_printing_nothing_when_it_cannot_tell():
    """"Cannot compute a ceiling" must be a refusal, not silence.

    Silence is indistinguishable from a deliberate opt-out at the shell, so a
    caller would create the unbounded container this all exists to prevent —
    and report success while doing it.
    """
    shim = ("import os, sys; "
            f"sys.path.insert(0, {str(_PROGRAMS)!r}); "
            "import _docker_memory as m; m.physical_memory_bytes = lambda: None; "
            "sys.exit(m._main(['--flags']))")
    r = _supervised([sys.executable, "-c", shim])
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "VIBEIC_DOCKER_MEMORY" in r.stdout


# ── the guard that has to survive future edits ──────────────────────────────

# The binary is spelled four ways in programs/: the literal, `docker_bin`, a
# bare `docker` parameter (analog_a6_librelane_drc._image_run), and a
# conditional expression that starts with one of those
# (`'docker' if docker == 'docker' else docker`, librelane_signoff's per-corner
# `sta` arm). The bare parameter escaped this guard with no ceiling until it was
# named here; the conditional was invisible to it until 2026-09-28 (it carried
# its flags, but only its own driven test would have noticed them go).
#
# Both words are matched in EITHER quote style. Until 2026-09-28 this pattern
# read only `"docker"` / `"run"`, and every one of librelane_contract.py's eight
# `[docker, 'run', ...]` sites — the per-step LibreLane runs, its config
# resolver and its image probes — created a container with no ceiling while
# this test passed. A guard that cannot see a site certifies it.
_RUN_ARGV = re.compile(
    r'''\[\s*(?:["']docker["']|docker_bin|docker)(?:\s+if\b[^,\n]*)?\s*,\s*["']run["']''')


def test_no_docker_run_escapes_the_ceiling():
    """Every container-creating argv in programs/ splices the flags in.

    Stated as a total rule with no allowlist on purpose. Some of these runs are
    one-line probes that could never grow to 100 GB, but "this one is small" is
    the judgement that has to be re-made correctly every time a call site is
    edited, and it is cheaper to make the rule unconditional than to maintain
    the exceptions.
    """
    escaped = []
    for path in sorted(_PROGRAMS.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        for m in _RUN_ARGV.finditer(src):
            window = src[m.start():m.start() + 400]
            if "docker_memory_flags" not in window:
                line = src[:m.start()].count("\n") + 1
                escaped.append(f"{path.name}:{line}")
    assert escaped == [], (
        "these `docker run` sites create a container with no memory ceiling; "
        "splice `*_dmem.docker_memory_flags()` in after the run verb: "
        f"{escaped}")


def test_the_guard_sees_every_spelling_of_a_docker_run_argv():
    """Calibration of the guard's own instrument, so a blind pattern reads red.

    Every combination of quote style on the binary and on the verb, each
    binary spelling, and a line break after the bracket must MATCH; a docker
    verb that creates no running container must not."""
    seen = ['["docker", "run"', "['docker', 'run'", '["docker", \'run\'',
            "['docker', \"run\"", '[docker, "run"', "[docker, 'run'",
            '[docker_bin, "run"', "[docker_bin, 'run'", "[\n        'docker', 'run'",
            "['docker' if docker == 'docker' else docker, 'run'",
            '[docker if docker else "docker", "run"']
    for text in seen:
        assert _RUN_ARGV.search(text), text
    for text in ('["docker", "image", "inspect"', "[docker, 'ps', '-q'",
                 "['docker', 'cp', '-L'", "[docker, 'rm', '-f'",
                 "['docker' if docker == 'docker' else docker, 'ps'"):
        assert not _RUN_ARGV.search(text), text


def test_the_ceiling_is_reachable_from_every_program_that_uses_it():
    """A spliced call that cannot import the helper is a NameError at runtime,
    on a path that only executes when real hardware work starts."""
    users = [p for p in sorted(_PROGRAMS.glob("*.py"))
             if "docker_memory_flags" in p.read_text(encoding="utf-8")]
    assert len(users) >= 8, f"expected the wiring across the plugin, found {users}"
    for path in users:
        r = _supervised(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0, {str(_PROGRAMS)!r}); "
             f"import {path.stem}"])
        assert r.returncode == 0, f"{path.name} does not import: {r.stderr[-600:]}"


# ── behavioural: the argv a real driver hands docker ────────────────────────

def test_mpw_precheck_argv_carries_the_ceiling(tmp_path):
    import mpw_precheck_driver as mpw
    for d in ("src", "input", "pdk", "run"):
        (tmp_path / d).mkdir()
    argv = mpw.build_docker_command(
        image="img:1", input_directory=tmp_path / "input",
        pdk_root=tmp_path / "pdk", pdk_path=tmp_path / "pdk",
        precheck_src=tmp_path / "src", rundir=tmp_path / "run",
        checks=["license"])
    assert argv[:2] == ["docker", "run"]
    assert "--memory" in argv and "--memory-swap" in argv
    assert argv[argv.index("--memory") + 1] == argv[argv.index("--memory-swap") + 1]


def test_caravel_harden_argv_carries_the_ceiling(tmp_path):
    import caravel_wrapper_harden_driver as cw
    argv = cw.build_harden_command(project_dir=tmp_path, design="user_project_wrapper",
                                   image="img:1", pdk_root=str(tmp_path), tag="t")
    assert "--memory" in argv
    # and the image is still the last thing before the entrypoint args
    assert argv.index("--memory") < argv.index("img:1")


def test_pdk_image_reader_argv_carries_the_ceiling(monkeypatch):
    """`_pdk_layer_authority.ImageReader` (bff32b63f, 15.5ic/37.5ic reading the
    PDK where the run's tools looked) starts a container per probe. Driven, not
    grepped: the argv it hands `subprocess.run` must carry both flags, equal,
    before the image."""
    import subprocess
    import _pdk_layer_authority as pla
    monkeypatch.setenv("VIBEIC_DOCKER_MEMORY", "3g")
    seen = []

    class _CP:
        returncode, stdout = 0, ""

    def _fake(argv, **_kw):
        seen.append(list(argv))
        return _CP()
    monkeypatch.setattr(subprocess, "run", _fake)
    rc, _ = pla.ImageReader._docker("img:1", ["ls", "/pdk"])
    assert rc == 0 and len(seen) == 1, seen
    argv = seen[0]
    assert argv[:2] == ["docker", "run"], argv
    assert argv[argv.index("--memory") + 1] == "3g", argv
    assert argv[argv.index("--memory-swap") + 1] == "3g", argv
    assert argv.index("--memory") < argv.index("img:1"), argv


def test_cdc_netlist_image_argv_carries_the_ceiling(tmp_path, monkeypatch):
    """`_cdc_netlist.build` (T91 step 3) runs yosys in the image when the host
    has none. Driven, not grepped: the argv it hands `subprocess.run` carries
    both flags, equal, before the image."""
    import _cdc_netlist as cdc
    monkeypatch.setenv("VIBEIC_DOCKER_MEMORY", "3g")
    monkeypatch.setattr(cdc.shutil, "which", lambda _name: None)
    seen = []

    class _CP:
        returncode, stdout, stderr = 1, "", ""

    def _fake(argv, **_kw):
        seen.append(list(argv))
        return _CP()
    monkeypatch.setattr(cdc.subprocess, "run", _fake)
    rtl = tmp_path / "top.v"
    rtl.write_text("module top; endmodule\n")
    with pytest.raises(cdc.Refusal, match="CDC_NETLIST_BUILD_FAILED"):
        cdc.build(tmp_path, [rtl], "top", image="img:1")
    assert len(seen) == 1, seen
    argv = seen[0]
    assert argv[:2] == ["docker", "run"], argv
    assert argv[argv.index("--memory") + 1] == "3g", argv
    assert argv[argv.index("--memory-swap") + 1] == "3g", argv
    assert argv.index("--memory") < argv.index("img:1"), argv


def test_technology_facts_argv_carries_the_ceiling(monkeypatch):
    """The tech-LEF read in `submission_template_fetch` (vibe-ic#2111).

    The structural sweep above names the site; this drives it, because the
    splice has a second property the sweep cannot see. The image is entered
    through its own entrypoint, whose help says `--skip` is ignored anywhere
    but FIRST — so the flags have to land BEFORE the image and never between
    the image and `--skip`. A splice that satisfied the sweep by putting them
    after the digest would run the entrypoint's full startup instead of the
    command, and the sweep would still be green.
    """
    import submission_template_fetch as stf

    class _Judged:
        ref = "repo@sha256:" + "0" * 64
        digest = "sha256:" + "0" * 64
        version = "0.0.0"
        why_not = ""

    seen = {}

    def _fake_run(argv, timeout=None):
        seen["argv"] = list(argv)
        return 3, "NO_TECH_LEF\n", ""

    monkeypatch.setattr(stf, "_run", _fake_run)
    import _eda_image
    monkeypatch.setattr(_eda_image, "judged_image",
                        lambda **kw: _Judged(), raising=True)

    stf.technology_facts("ihp-sg13g2", image="", allow_pull=False)
    argv = seen.get("argv")
    assert argv, "technology_facts never reached its `docker run`"
    assert argv[:2] == ["docker", "run"], argv
    assert "--memory" in argv and "--memory-swap" in argv, argv
    assert argv[argv.index("--memory") + 1] == \
        argv[argv.index("--memory-swap") + 1], argv
    image_at = argv.index(_Judged.ref)
    assert argv.index("--memory") < image_at, (
        f"the ceiling was spliced AFTER the image, so it is an argument to "
        f"the entrypoint and not to docker: {argv}")
    assert argv[image_at + 1] == "--skip", (
        f"`--skip` is no longer the first argument after the image; the "
        f"image entrypoint ignores it anywhere else: {argv}")


def _ll_design(root):
    """The fewest declared inputs `librelane_contract.emit_config` accepts."""
    import json
    docs = root / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    (docs / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({"clock_domains": [
        {"role": "primary", "period_ns": 10, "source_pin": "clk"}]}))
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"top_module": "block"}))
    (docs / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps({"fields": {}}))
    decl = root / "input" / "submission_template" / "tapeout_declaration.json"
    decl.parent.mkdir(parents=True)
    decl.write_text(json.dumps({"answers": {}}))
    return root


def test_librelane_contract_argv_carries_the_ceiling(tmp_path, monkeypatch):
    """Every container `librelane_contract` creates, driven through the real
    function that creates it (the per-step LibreLane run, the config resolvers,
    the image probes, the flow-order read, the PDN script read and the direct ->
    LibreLane view conversion). The heaviest container the plugin starts is a
    LibreLane step, and all eight of these sites ran unbounded behind a sweep
    that could not read single quotes; this names each one by its function so a
    site that loses the splice is reported by name, not as a count."""
    import json
    from types import SimpleNamespace
    import librelane_contract as ll
    monkeypatch.setenv("VIBEIC_DOCKER_MEMORY", "3g")
    image = "img:w15"
    seen = []

    def _recorder(reply):
        def _fake(argv, **_kw):
            argv = list(argv)
            seen.append((_fake.site, argv))
            return reply(argv)
        return _fake

    def _drive(site, reply, call):
        fake = _recorder(reply)
        fake.site = site
        monkeypatch.setattr(ll.subprocess, "run", fake)
        return call()

    ok = lambda stdout="": (lambda argv: SimpleNamespace(returncode=0, stdout=stdout, stderr=""))

    # image_capability: the CLI probe (rc 0), then the Tcl alias probe (rc 1:
    # recorded NOT_MEASURED, not a refusal) — two containers.
    monkeypatch.setattr(ll, "_CAPABILITY", {})
    replies = iter([0, 1])
    _drive("image_capability", lambda argv: SimpleNamespace(
        returncode=next(replies), stdout="", stderr=""),
        lambda: ll.image_capability(image))

    project = _ll_design(tmp_path / "design")
    folder = tmp_path / "convert"
    folder.mkdir()
    _drive("_openroad_convert", ok(), lambda: ll._openroad_convert(
        project, image, {"TECH_LEFS": {"nom_*": str(tmp_path / "t.lef")}},
        ["exit"], folder, "def_to_odb", [], "docker"))

    monkeypatch.setattr(ll, "image_capability", lambda *a: None)
    pdk = "pdkA"
    (tmp_path / "pdk" / pdk).mkdir(parents=True)
    with pytest.raises(ll.Refusal, match="LL_CONFIG_RESOLUTION_FAILED"):
        _drive("resolve_step_configs",
               lambda argv: SimpleNamespace(returncode=1, stdout="", stderr=""),
               lambda: ll.resolve_step_configs(project, image, pdk, ["X.Step"],
                                               pdk_root=tmp_path / "pdk"))

    registry = json.loads((_PROGRAMS / "pdk_registry.json").read_text())
    entries = registry.get("pdks", [])
    if isinstance(entries, dict):
        entries = [dict(v, name=k) for k, v in entries.items() if isinstance(v, dict)]
    ringed = next(e["name"] for e in entries
                  if (e.get("pdn_ring") or {}).get("connect_to_pad_layers")
                  and (e.get("pdn_ring") or {}).get("connects"))
    pdn_probe = json.dumps({ll._PDN_PAYLOAD_KEY: "add_pdn_connect -grid g\n"}) + "\n"
    assert _drive("emit_pdn_cfg", ok(pdn_probe),
                  lambda: ll.emit_pdn_cfg(image, ringed, tmp_path / "pdn.tcl"))

    assert _drive("flow_segment", ok('["A.One", "B.Two"]\n'),
                  lambda: ll.flow_segment(image, "A.One", "B.Two")) == ["A.One", "B.Two"]

    resolved = tmp_path / "resolved.json"
    resolved.write_text("{}")
    _drive("resolve_step_config", ok(), lambda: ll.resolve_step_config(
        project, image, tmp_path / "source.json", resolved))

    netlist = project / "block.nl.v"
    netlist.write_text("module block; endmodule\n")
    state = project / "initial.json"
    state.write_text(json.dumps({"nl": str(netlist)}))
    config = project / "config.json"
    config.write_text(json.dumps({"meta": {"step": "OpenROAD.Floorplan"}}))

    def _step(argv):
        out = Path(argv[argv.index("-o") + 1])
        (out / "state_out.json").write_text(json.dumps({"nl": str(netlist)}))
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    _drive("run_chain", _step, lambda: ll.run_chain(
        project, image, [("OpenROAD.Floorplan", config, state)], pdk_root='/pdk'))

    sites = [site for site, _ in seen]
    assert sites == ["image_capability", "image_capability", "_openroad_convert",
                     "resolve_step_configs", "emit_pdn_cfg", "flow_segment",
                     "resolve_step_config", "run_chain"], sites
    for site, argv in seen:
        assert argv[:2] == ["docker", "run"], (site, argv)
        assert "--memory" in argv and "--memory-swap" in argv, (
            f"{site} creates a container with no memory ceiling: {argv}")
        assert argv[argv.index("--memory") + 1] == "3g", (site, argv)
        assert argv[argv.index("--memory-swap") + 1] == "3g", (site, argv)
        image_at = argv.index(image)
        assert argv.index("--memory") < image_at, (
            f"{site}: the ceiling is an argument to the entrypoint, not to "
            f"docker: {argv}")
    convert = next(argv for site, argv in seen if site == "_openroad_convert")
    assert convert[convert.index(image) + 1] == "--skip", (
        f"`--skip` must stay the first argument after the image: {convert}")


def test_the_installer_script_refuses_without_the_helper(tmp_path):
    """tools/vibeic-eda/restart-eda.sh must not fall back to unbounded when the
    helper it reads the ceiling from is absent."""
    script = _REPO / "tools" / "vibeic-eda" / "restart-eda.sh"
    if not script.is_file():
        pytest.skip(f"{script} not in this checkout")
    body = script.read_text(encoding="utf-8")
    assert "_docker_memory.py" in body, (
        "the installer computes its own ceiling instead of reading the shared "
        "one; the two will drift")
    assert re.search(r'die "missing \$\{?_MEMTOOL', body) or "die \"missing ${_MEMTOOL}" in body, (
        "a missing helper must be a refusal, not an unbounded container")
    assert "MEMFLAGS" in body and 'RUN+=( "${MEMFLAGS[@]}" )' in body, (
        "the flags are computed but never reach the `docker run` argv")


# ── the budget is OPT-IN, and the default must not move ────────────────────
#
# Added 2026-09-14 after 8HD-8 (192.168.1.114) was promised 264 GB of a 126 GB
# host: three containers, one ngspice apiece at ~25 GB, each correctly under
# its own 88 GB ceiling. 38 MB available, swap 100 % full, load 220. Every TCP
# port still answered its handshake, so every liveness probe read the host as
# healthy while no userspace process could reply, for forty minutes.
#
# The module's own docstring had already named this case and deferred it on
# purpose. These tests hold the line it drew: the arithmetic exists, and the
# DEFAULT does not change.

_REAL_RESERVED = dm.reserved_by_running_containers


class _FakeRun:
    """A `subprocess.run` that answers the two calls the helper makes."""

    def __init__(self, ids, limits, rc=0, boom=False):
        self._ids, self._limits, self._rc, self._boom = ids, limits, rc, boom

    def __call__(self, argv, **kw):
        if self._boom:
            raise OSError("docker is not installed")
        out = " ".join(self._ids) if argv[:2] == ["docker", "ps"] \
            else "\n".join(str(v) for v in self._limits)
        return subprocess.CompletedProcess(argv, self._rc, out, "")


def test_a_running_sibling_is_counted():
    four_gb = 4 * 1024 ** 3
    assert _REAL_RESERVED(_FakeRun(["a"], [four_gb])) == four_gb


def test_a_sibling_with_no_ceiling_of_its_own_counts_for_nothing():
    # HostConfig.Memory is 0 for an unbounded container. It is consuming real
    # memory, but docker never PROMISED it anything, so there is no promise to
    # deduct and 0 is the only honest answer.
    assert _REAL_RESERVED(_FakeRun(["a"], [0])) == 0


def test_nothing_running_reserves_nothing():
    assert _REAL_RESERVED(_FakeRun([], [])) == 0


def test_docker_unreachable_counts_zero_rather_than_refusing():
    assert _REAL_RESERVED(_FakeRun([], [], boom=True)) == 0
    assert _REAL_RESERVED(_FakeRun(["a"], [1], rc=1)) == 0


def test_the_default_is_still_a_per_container_ceiling_not_a_budget(monkeypatch):
    """The load-bearing regression guard: opting in must be a CHOICE."""
    total = 128 * 1024 ** 3
    monkeypatch.setattr(dm, "physical_memory_bytes", lambda: total)
    monkeypatch.setattr(dm, "reserved_by_running_containers",
                        lambda *a, **k: 40 * 1024 ** 3)
    assert int(dm.memory_limit({})) == total * dm.DEFAULT_FRACTION // 100


def test_opting_in_subtracts_what_the_siblings_already_hold(monkeypatch):
    total = 128 * 1024 ** 3
    monkeypatch.setattr(dm, "physical_memory_bytes", lambda: total)
    monkeypatch.setattr(dm, "reserved_by_running_containers",
                        lambda *a, **k: 40 * 1024 ** 3)
    on = int(dm.memory_limit({"VIBEIC_DOCKER_MEMORY_SHARED": "1"}))
    assert on == total * dm.DEFAULT_FRACTION // 100 - 40 * 1024 ** 3


def test_opted_in_three_siblings_cannot_be_promised_more_than_the_host(monkeypatch):
    """The incident, as arithmetic."""
    total = 128 * 1024 ** 3
    monkeypatch.setattr(dm, "physical_memory_bytes", lambda: total)
    env = {"VIBEIC_DOCKER_MEMORY_SHARED": "1"}
    handed_out = 0
    for _ in range(3):
        taken = handed_out
        monkeypatch.setattr(dm, "reserved_by_running_containers",
                            lambda *a, _t=taken, **k: _t)
        handed_out += int(dm.memory_limit(env))
    assert handed_out <= total, (
        "three containers were promised %.0f GB of a %.0f GB host"
        % (handed_out / 1024 ** 3, total / 1024 ** 3))


def test_an_explicit_ceiling_wins_over_the_budget_arithmetic(monkeypatch):
    # A job that genuinely needs the machine must keep getting it. The budget
    # narrows the DERIVED share only.
    monkeypatch.setattr(dm, "reserved_by_running_containers",
                        lambda *a, **k: 120 * 1024 ** 3)
    env = {"VIBEIC_DOCKER_MEMORY_SHARED": "1", "VIBEIC_DOCKER_MEMORY": "110g"}
    assert dm.memory_limit(env) == "110g"
    env["VIBEIC_DOCKER_MEMORY"] = "unlimited"
    assert dm.memory_limit(env) is None


def test_the_budget_never_falls_below_the_floor_however_full_the_host(monkeypatch):
    total = 128 * 1024 ** 3
    monkeypatch.setattr(dm, "physical_memory_bytes", lambda: total)
    monkeypatch.setattr(dm, "reserved_by_running_containers", lambda *a, **k: total)
    assert int(dm.memory_limit({"VIBEIC_DOCKER_MEMORY_SHARED": "1"})) == dm.FLOOR_BYTES
