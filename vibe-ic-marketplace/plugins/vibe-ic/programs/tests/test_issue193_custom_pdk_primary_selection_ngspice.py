"""vibe-ic#193 — the ngspice verification the issue says is needed.

THE ISSUE, RESTATED
===================
`test_analog_pdk_lib_include_farm.py::test_no_farm_dir_keeps_the_raw_path` is
`@pytest.mark.xfail(strict=False)` because it asserts `model_lib ==
spice_libs[0]` (FIRST-STAGED lib / entry shim wins) while HEAD's
`custom_family_context` ranks by DEVICE-DEFINING lib (#149 / v1.4.58). The
issue parks the divergence as "two plausible arguments, unverifiable without
ngspice — pending owner decision". An `xfail(strict=False)` that never resolves
is a permanent unknown, so this file MEASURES the thing instead of arguing it.

**IT DECIDES NOTHING.** No runtime selection is changed here, and the xfail
stays exactly where the owner left it. What this file removes is the
"unverifiable" clause: it stages the issue's OWN fixture, asks HEAD which lib
it elects, and hands BOTH candidates to a real ngspice — so the owner decides
from a measurement.

WHAT WAS MEASURED (ngspice-46+, vibeic-eda:0.2.30)
==================================================
Same deck, same circuit, one line different: `.lib <candidate> tt`.

  case                                HEAD elects  shim deck  device-lib deck
  ----------------------------------  -----------  ---------  ---------------
  A split dirs, self-contained dev     device lib   FAILS      LOADS + SOLVES
      (this IS the xfail fixture)                   (Could not find library file)
  B same dir,  self-contained dev      SHIM         LOADS      LOADS
  C same dir,  dev needs shim param    SHIM         LOADS      FAILS
                                                               (Undefined parameter [rsheet])
  D split dirs, dev needs shim param   device lib   FAILS      FAILS
  E same dir,  dev needs shim param,   SHIM         LOADS      FAILS
    staged [dev, shim] so                           ^ HEAD     ^ spice_libs[0]
    spice_libs[0] IS the device lib

Findings, each pinned by a test below:

  1. The two policies AGREE whenever the include closure is reachable AND the
     entry shim happens to be staged first (B, C). The `n_defines` key ties and
     `max` keeps the first maximal lib, which IS `spice_libs[0]` — there the
     two policies are literally the same function.
  2. Case E is the genuine head-to-head: closure fully reachable, but the
     device lib staged first, so `spice_libs[0]` and the ranking disagree. HEAD
     elects the shim and it SOLVES (v(d)=0.9V); `spice_libs[0]` names the
     device lib and ngspice rejects it with `Undefined parameter [rsheet]`.
     Where the policies really differ, the measured answer favours HEAD.
  3. They also diverge when the libs are staged cross-directory (A, D), and
     there `spice_libs[0]` names a deck ngspice CANNOT LOAD AT ALL.
  4. The reason A behaves that way is that HEAD's ranking tracks ngspice's OWN
     file resolution. `transitive_subckts` resolves a bare `.lib
     mfx180_dev.lib` against the INCLUDING FILE's directory; so does ngspice.
     When the sibling is elsewhere BOTH lose it — the shim's closure collapses
     2 -> 0 and its deck dies with "Could not find library file". HEAD elects
     the lib that is loadable, which is not a policy choice at all.
  5. Case D is nobody's win: neither candidate runs. That is what the include
     farm exists for — and no production caller passes `farm_dir`, so the
     runtime cannot reach the repair.

The container-backed tests SKIP (never fail) when no ngspice is available; the
pure-python ones always run and pin the mechanism.

WHICH WORLD IS THE RUNTIME IN? (the second half of this file)
=============================================================
BOTH strategies are live in the shipped module, and `farm_dir` is the ONLY
switch between them:

    farm_dir is None -> primary = max(readable, key=_primary_rank)   (HEAD)
    farm_dir is set  -> primary = res["spice_lib"] == spice_libs[0]  (afec),
                        loaded through the include farm

Three things follow, each pinned below and each MEASURED on this tree:

  A. The claim "no production caller passes farm_dir" was previously checked by
     grepping for `farm_dir=` / `build_lib_include_farm(`. Passing it
     POSITIONALLY defeats that grep entirely: wiring the first-staged strategy
     into the sole production caller with a one-line positional edit left the
     analog/PDK sweep at 1661 passed / 10 skipped / 1 xfailed, rc 0. The check
     is now AST-based, with the positional index read from the signature.
  B. The two strategies elect a DIFFERENT primary lib in 8 of the 17 custom-PDK
     configurations this repo tracks — including the rung-2 container-installed
     shape, where `spice_libs[0]` is an auxiliary lib defining ZERO devices.
     The divergence changes the answer in just under half the corpus.
  C. A DeckContext now records WHICH strategy elected its `model_lib`
     (`primary_policy`), so an artefact can no longer be silent about the world
     it came from.

None of that decides the owner's question. It makes the two answers
distinguishable — which they were not.
"""
from __future__ import annotations

import ast
import inspect
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGS))

import analog_pdk_deck_context as APDC  # noqa: E402

NCH = "myfoundry_x180_nch"
PCH = "myfoundry_x180_pch"
SECTIONS = ("ss", "tt", "ff")


# --------------------------------------------------------------- the fixture
def _device_lib(self_contained: bool = True) -> str:
    """The device-defining lib. `self_contained=False` makes each section need
    a `.param` only the entry shim's composed section supplies (v1.4.58's
    shape). Synthetic, chip-AGNOSTIC — no vendor/SKU/NDA content."""
    out = ["* synthetic device lib (NO NDA content)"]
    for sec in SECTIONS:
        out.append(f".lib {sec}")
        for dev in (NCH, PCH):
            out.append(f".subckt {dev} d g s b w=1 l=1")
            out.append("Rchan d s 1k" if self_contained
                       else "Rchan d s 'rsheet*l/w'")
            out.append(".ends")
        out.append(".endl")
    return "\n".join(out) + "\n"


def _shim_lib(device_basename: str, self_contained: bool = True) -> str:
    """The composed corner shim: owns the corner sections, pulls devices from a
    SIBLING lib by BARE RELATIVE NAME — the entry-point shape."""
    out = ["* synthetic composed corner shim (NO NDA content)"]
    for sec in SECTIONS:
        out.append(f".lib {sec}")
        if not self_contained:
            out.append(".param rsheet=1000")
        out.append(f".lib {device_basename} {sec}")
        out.append(".endl")
    return "\n".join(out) + "\n"


def _stage(base: Path, *, split: bool, self_contained: bool,
           device_first: bool = False):
    """Stage the fixture and return (res, shim, dev). `split=True` reproduces
    `test_analog_pdk_lib_include_farm._stage_split` exactly. `device_first`
    reverses the staging order so `spice_libs[0]` is the DEVICE lib — the only
    arrangement in which the two policies disagree with the closure intact."""
    a = base / "bridge"
    b = (base / "models") if split else a
    a.mkdir(parents=True, exist_ok=True)
    b.mkdir(parents=True, exist_ok=True)
    shim, dev = a / "mfx180_corners.lib", b / "mfx180_dev.lib"
    shim.write_text(_shim_lib(dev.name, self_contained))
    dev.write_text(_device_lib(self_contained))
    order = [dev, shim] if device_first else [shim, dev]
    res = {"available": True, "source": "project_custom_pdk",
           "family": "myfoundryx180", "target": "MyFoundry X180 (custom node)",
           "spice_libs": [str(p) for p in order], "spice_lib": str(order[0]),
           "drc_deck": None, "lvs_deck": None}
    return res, shim, dev


def _reader(p):
    try:
        return Path(p).read_text()
    except OSError:
        return None


# =====================================================================
# MECHANISM (pure python, always runs). Why the two policies disagree.
# =====================================================================

def test_the_shims_closure_collapses_only_when_staged_cross_directory(tmp_path):
    """The whole divergence in one measurement: the shim reaches both devices
    when its sibling is co-located and NEITHER when it is not, because
    `transitive_subckts` resolves a bare relative `.lib` against the including
    file's directory.

    MUTATION THIS CATCHES: resolving includes against the process cwd or a
    search path instead — the collapse disappears, and with it the whole
    premise that the fixture is measuring a policy at all.
    """
    _, shim_s, dev_s = _stage(tmp_path / "split", split=True,
                              self_contained=True)
    _, shim_c, dev_c = _stage(tmp_path / "same", split=False,
                              self_contained=True)

    split_reach = APDC.transitive_subckts(str(shim_s), shim_s.read_text(),
                                          _reader)
    same_reach = APDC.transitive_subckts(str(shim_c), shim_c.read_text(),
                                         _reader)
    assert split_reach == {}, (
        f"cross-directory: the shim must reach nothing, got {split_reach}")
    assert set(same_reach) == {NCH, PCH}, same_reach
    # The device lib is unaffected either way — it has no includes.
    for d in (dev_s, dev_c):
        assert set(APDC.transitive_subckts(str(d), d.read_text(), _reader)) \
            == {NCH, PCH}


def test_head_and_the_xfail_agree_once_the_libs_are_co_located(tmp_path):
    """FINDING 1. Co-located and shim-first, HEAD elects the SHIM — exactly
    what the xfail test asserts, so there is no disagreement in this
    arrangement at all.

    MEASURED CAVEAT, stated because it changes what this proves: `n_defines`
    TIES at 2 here, and `max` keeps the first maximal lib, which is
    `spice_libs[0]`. Dropping `is_aggregator`, or `n_composed`, or reducing the
    key to `n_defines` alone, ALL still elect the shim — those tiebreaks are
    not load-bearing in this arrangement (measured; do not claim otherwise).
    Case E below is where they become load-bearing.

    MUTATION THIS CATCHES: ranking by the lib's OWN device count ahead of its
    transitive closure (`return (own_dev, n_defines, ...)`) — a device-lib-first
    ranking. That is caught here and in the two co-located ngspice cases.
    """
    res, shim, _dev = _stage(tmp_path, split=False, self_contained=True)
    ctx = APDC.custom_family_context(res)
    assert ctx.model_lib == str(shim), (
        "co-located, HEAD must elect the composed entry shim; got "
        f"{ctx.model_lib}")
    assert ctx.model_lib == res["spice_libs"][0], (
        "and that IS spice_libs[0] here — the two policies coincide")


def test_the_policies_genuinely_disagree_only_when_the_device_lib_is_staged_first(
        tmp_path):
    """FINDING 2 (mechanism half). Reverse the staging order and the closure
    stays intact, so this is the real head-to-head: `spice_libs[0]` is now the
    DEVICE lib while the ranking still elects the shim.

    MUTATION THIS CATCHES: any collapse of the ranking to 'first staged lib' —
    the whole policy the xfail test encodes. Here that changes the answer.
    """
    res, shim, dev = _stage(tmp_path, split=False, self_contained=True,
                            device_first=True)
    assert res["spice_libs"][0] == str(dev)
    assert APDC.custom_family_context(res).model_lib == str(shim), (
        "with the closure reachable, HEAD elects the composed entry shim "
        "regardless of staging order — this is where is_aggregator/n_composed "
        "actually decide")


def test_head_diverges_from_spice_libs0_only_in_the_split_staging(tmp_path):
    """FINDING 2, the divergence itself, pinned so it cannot drift silently.
    This is the xfail fixture's exact shape.

    NOT A POLICY ASSERTION: it records WHAT HEAD DOES today so the issue's
    'HEAD 現狀' claim is executable rather than prose.
    """
    res, shim, dev = _stage(tmp_path, split=True, self_contained=True)
    ctx = APDC.custom_family_context(res)
    assert ctx.model_lib == str(dev), (
        f"HEAD is documented to elect the device-defining lib here; got "
        f"{ctx.model_lib}")
    assert ctx.model_lib != res["spice_libs"][0] == str(shim)


# =====================================================================
# THE NGSPICE MEASUREMENT. Skipped, never failed, without a simulator.
# =====================================================================

_DECK = """\
* vibe-ic#193 primary-selection probe — the ONLY variable is the .lib line
.lib {primary} tt
V1 vdd 0 1.8
R1 vdd d 1k
R2 g 0 1meg
X1 d g 0 0 {nch} w=1 l=1
.control
op
print v(d)
.endc
.end
"""


def _verbatim_ngspice_container():
    """(container, host_root, ngspice_bin) for a RUNNING container exposing
    ngspice through a writable bind-mount whose Source == Destination, so a
    host path is valid inside unchanged. None -> caller SKIPS.

    Same shape as test_hspice_lib_ngspice_normalize._verbatim_container.
    """
    if not shutil.which("docker"):
        return None
    try:
        names = subprocess.run(["docker", "ps", "--format", "{{.Names}}"],
                               capture_output=True, text=True,
                               timeout=30).stdout.split()
    except Exception:
        return None
    for name in names:
        try:
            mounts = subprocess.run(
                ["docker", "inspect", name, "--format",
                 "{{range .Mounts}}{{.Source}}::{{.Destination}}::{{.RW}}\n{{end}}"],
                capture_output=True, text=True, timeout=30).stdout
            probe = subprocess.run(
                ["docker", "exec", name, "bash", "-lc",
                 "command -v ngspice || ls /foss/tools/*/bin/ngspice "
                 "2>/dev/null | head -1"],
                capture_output=True, text=True, timeout=60)
        except Exception:
            continue
        ng = next((l.strip() for l in (probe.stdout or "").splitlines()
                   if l.strip().startswith("/") and "ngspice" in l), "")
        if not ng:
            continue
        for row in mounts.splitlines():
            parts = row.split("::")
            if len(parts) == 3 and parts[0] and parts[0] == parts[1] \
                    and parts[2] == "true" and os.access(parts[0], os.W_OK):
                return name, Path(parts[0]), ng
    return None


def _simulate(container, ngspice, deck: Path) -> dict:
    cp = subprocess.run(
        ["docker", "exec", container, "bash", "-lc",
         f"cd {deck.parent} && {ngspice} -b {deck.name} 2>&1; echo RC=$?"],
        capture_output=True, text=True, timeout=180)
    out = cp.stdout or ""
    rc = next((int(l[3:]) for l in out.splitlines() if l.startswith("RC=")), 999)
    low = out.lower()
    return {"rc": rc, "out": out,
            "lib_not_found": "not found" in low and "library file" in low,
            "undefined_param": "undefined parameter" in low,
            "solved": "v(d) =" in low}


@pytest.fixture(scope="module")
def ngspice_env():
    env = _verbatim_ngspice_container()
    if env is None:
        pytest.skip("no running container with ngspice + a writable verbatim "
                    "bind-mount — the #193 primary-selection measurement is "
                    "NOT exercised here (skipped, not assumed)")
    return env


@pytest.fixture
def workdir(ngspice_env):
    _c, host_root, _n = ngspice_env
    work = host_root / ".vibeic_issue193_test"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    try:
        yield work
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_ngspice_split_staging_only_head_pick_loads(ngspice_env, workdir):
    """CASE A — the xfail fixture's exact shape, on a real simulator.

    The candidate the xfail test asserts (`spice_libs[0]`, the shim) produces a
    deck ngspice cannot load at all; HEAD's candidate solves. This is the
    measurement the issue asked for, and it is an asymmetry, not a preference.
    """
    container, _root, ngspice = ngspice_env
    res, shim, dev = _stage(workdir, split=True, self_contained=True)
    assert APDC.custom_family_context(res).model_lib == str(dev)

    (workdir / "shim.sp").write_text(_DECK.format(primary=shim, nch=NCH))
    (workdir / "dev.sp").write_text(_DECK.format(primary=dev, nch=NCH))
    shim_r = _simulate(container, ngspice, workdir / "shim.sp")
    dev_r = _simulate(container, ngspice, workdir / "dev.sp")

    assert shim_r["rc"] != 0 and shim_r["lib_not_found"], (
        "spice_libs[0] must be UNLOADABLE in the split staging (ngspice "
        f"resolves includes relative to the including file too):\n"
        f"{shim_r['out'][-600:]}")
    assert dev_r["rc"] == 0 and dev_r["solved"], (
        f"HEAD's pick must solve:\n{dev_r['out'][-600:]}")


def test_ngspice_co_located_both_candidates_load(ngspice_env, workdir):
    """CASE B — the CONTROL. Same bytes, one directory. Both decks solve, so
    case A's asymmetry is caused by the STAGING, not by the libs' content.

    Without this control, case A alone could be read as 'the shim is a bad
    entry point', which the measurement does not support.
    """
    container, _root, ngspice = ngspice_env
    res, shim, dev = _stage(workdir, split=False, self_contained=True)
    assert APDC.custom_family_context(res).model_lib == str(shim)

    (workdir / "shim.sp").write_text(_DECK.format(primary=shim, nch=NCH))
    (workdir / "dev.sp").write_text(_DECK.format(primary=dev, nch=NCH))
    for label, r in (("shim", _simulate(container, ngspice, workdir / "shim.sp")),
                     ("dev", _simulate(container, ngspice, workdir / "dev.sp"))):
        assert r["rc"] == 0 and r["solved"], f"{label}:\n{r['out'][-600:]}"


def test_ngspice_co_located_non_self_contained_only_the_shim_loads(ngspice_env,
                                                                   workdir):
    """CASE C — the case that JUSTIFIES electing the entry shim (v1.4.58).

    The device lib's sections need a `.param` only the shim's composed section
    supplies. Electing the device lib dies with `Undefined parameter`; electing
    the shim solves. HEAD elects the shim here, so HEAD is on the right side of
    this one too — the direction the xfail test also wants.
    """
    container, _root, ngspice = ngspice_env
    res, shim, dev = _stage(workdir, split=False, self_contained=False)
    assert APDC.custom_family_context(res).model_lib == str(shim)

    (workdir / "shim.sp").write_text(_DECK.format(primary=shim, nch=NCH))
    (workdir / "dev.sp").write_text(_DECK.format(primary=dev, nch=NCH))
    shim_r = _simulate(container, ngspice, workdir / "shim.sp")
    dev_r = _simulate(container, ngspice, workdir / "dev.sp")

    assert shim_r["rc"] == 0 and shim_r["solved"], shim_r["out"][-600:]
    assert dev_r["rc"] != 0 and dev_r["undefined_param"], (
        "a device lib that needs the entry shim's .param must FAIL when it is "
        f"elected as primary:\n{dev_r['out'][-600:]}")


def test_ngspice_reversed_staging_head_solves_where_spice_libs0_does_not(
        ngspice_env, workdir):
    """CASE E — THE DECISIVE MEASUREMENT for the owner's decision.

    Everything reachable, nothing degenerate: co-located libs, but staged
    [device, shim] so `spice_libs[0]` really is the device lib. The two
    policies now name DIFFERENT libs with no missing-file artefact to explain
    it away, and the simulator separates them cleanly:

        HEAD           -> the composed shim   -> solves, v(d) = 0.9 V
        spice_libs[0]  -> the device lib      -> Undefined parameter [rsheet]

    This is the case the issue could not decide from argument. It does not
    settle the owner's policy question by itself — it supplies the evidence
    that the two candidate policies are NOT equivalent, and which way the
    simulator falls on this shape.
    """
    container, _root, ngspice = ngspice_env
    res, shim, dev = _stage(workdir, split=False, self_contained=False,
                            device_first=True)
    assert res["spice_libs"][0] == str(dev)
    assert APDC.custom_family_context(res).model_lib == str(shim)

    (workdir / "shim.sp").write_text(_DECK.format(primary=shim, nch=NCH))
    (workdir / "dev.sp").write_text(_DECK.format(primary=dev, nch=NCH))
    head_r = _simulate(container, ngspice, workdir / "shim.sp")
    first_staged_r = _simulate(container, ngspice, workdir / "dev.sp")

    assert head_r["rc"] == 0 and head_r["solved"], (
        f"HEAD's elected primary must solve:\n{head_r['out'][-600:]}")
    assert first_staged_r["rc"] != 0 and first_staged_r["undefined_param"], (
        "spice_libs[0] must FAIL here — this is the head-to-head the issue "
        f"asked to measure:\n{first_staged_r['out'][-600:]}")


def test_ngspice_split_and_non_self_contained_neither_candidate_loads(
        ngspice_env, workdir):
    """CASE D — the honest negative. Neither policy rescues a split-staged,
    non-self-contained PDK; only co-locating the closure does. Recorded so the
    owner's decision is not mistaken for a fix for this case.
    """
    container, _root, ngspice = ngspice_env
    _res, shim, dev = _stage(workdir, split=True, self_contained=False)
    (workdir / "shim.sp").write_text(_DECK.format(primary=shim, nch=NCH))
    (workdir / "dev.sp").write_text(_DECK.format(primary=dev, nch=NCH))
    shim_r = _simulate(container, ngspice, workdir / "shim.sp")
    dev_r = _simulate(container, ngspice, workdir / "dev.sp")
    assert shim_r["rc"] != 0 and shim_r["lib_not_found"], shim_r["out"][-400:]
    assert dev_r["rc"] != 0 and dev_r["undefined_param"], dev_r["out"][-400:]


# =====================================================================
# WHICH WORLD IS THE RUNTIME IN? — both strategies are live, and `farm_dir`
# is the only switch between them.
# =====================================================================

def _farm_dir_position(fn) -> int:
    """The POSITIONAL index of `farm_dir` in `fn`'s signature, read from the
    signature itself so a re-ordered parameter list cannot silently defeat the
    scan below."""
    params = list(inspect.signature(fn).parameters)
    assert "farm_dir" in params, (
        f"{fn.__name__} no longer takes farm_dir — the first-staged strategy "
        f"moved; re-derive this scan. params={params}")
    return params.index("farm_dir")


def test_no_production_caller_wires_the_first_staged_strategy():
    """BOTH primary-selection strategies are live in the shipped runtime:

        farm_dir is None  -> primary = max(readable, key=_primary_rank)
                             (device-defining rank, #149 / v1.4.58)
        farm_dir is set   -> primary = res["spice_lib"] == spice_libs[0],
                             loaded through the include farm (the afec policy)

    So "which policy does the product use?" is decided by ONE argument, and
    this test is the repo's answer. It asserts the CURRENT wiring — no
    production caller passes farm_dir, so only the device-defining rank is
    reachable — and it is the thing that must go red the day that changes.

    AST, NOT GREP, and the difference is measured, not stylistic. The previous
    version of this test matched the source lines `build_lib_include_farm(` and
    `farm_dir=`. Passing farm_dir POSITIONALLY —
        resolve_deck_context(pdk, res, required, reader, bdir / "_libfarm")
    — wires the first-staged strategy into the sole production caller and
    matches NEITHER pattern. Measured on this tree with exactly that one-line
    change: 1661 passed / 10 skipped / 1 xfailed, rc 0. The repo could not tell
    which world it was in.
    """
    targets = {
        "custom_family_context": _farm_dir_position(APDC.custom_family_context),
        "resolve_deck_context": _farm_dir_position(APDC.resolve_deck_context),
        "build_lib_include_farm": None,   # taking a farm dir IS its signature
    }
    defining = Path(APDC.__file__).name
    scanned, calls, wired = 0, 0, []
    for py in sorted(PROGS.glob("*.py")):
        if py.name == defining:
            continue                       # the module that DEFINES the switch
        try:
            tree = ast.parse(py.read_text(errors="replace"))
        except SyntaxError:                # a program that does not parse is
            continue                       # not a caller of anything
        scanned += 1
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = (fn.attr if isinstance(fn, ast.Attribute)
                    else fn.id if isinstance(fn, ast.Name) else None)
            if name not in targets:
                continue
            calls += 1
            idx = targets[name]
            passes = ("farm_dir" in [k.arg for k in node.keywords]
                      or idx is None                       # the farm builder
                      or len(node.args) > idx)             # POSITIONAL farm_dir
            if passes:
                wired.append(f"{py.name}:{node.lineno}: {name}(...)")

    # A gate that examined nothing must not report PASS.
    assert scanned >= 2, (
        f"vacuous: only {scanned} production module(s) parsed — the scan found "
        f"nothing because it looked at nothing, not because nothing is wired")
    assert calls >= 1, (
        f"vacuous: {scanned} modules parsed but ZERO calls to {sorted(targets)} "
        f"were seen; the runtime entry point was renamed or moved and this scan "
        f"is no longer measuring the wiring it claims to measure")

    assert wired == [], (
        f"the first-staged-lib strategy is now REACHABLE from production "
        f"({len(wired)} of {calls} call sites across {scanned} modules). That "
        f"is the vibe-ic#193 architectural decision being taken by a call-site "
        f"edit. If it is intended, say so here and re-measure the census in "
        f"test_the_two_strategies_disagree_on_the_tracked_corpus.\n"
        + "\n".join(wired))

    # And the strategy is genuinely IMPLEMENTED, not merely unreferenced — the
    # gap is WIRING, not capability, which is what makes it a live decision.
    assert callable(APDC.build_lib_include_farm)


def test_the_context_records_which_strategy_elected_the_primary(tmp_path):
    """A context (and every artefact derived from it) must say WHICH of the two
    live strategies produced its `model_lib`. Before this, two runs that elected
    DIFFERENT libs by DIFFERENT policies were indistinguishable downstream.

    Records; decides nothing. Both values are asserted, so neither policy can be
    quietly relabelled as the other.
    """
    res, shim, dev = _stage(tmp_path, split=True, self_contained=True)

    off = APDC.custom_family_context(res)
    assert off.primary_policy == APDC.PRIMARY_BY_DEVICE_RANK
    assert off.model_lib == str(dev)
    assert APDC.PRIMARY_BY_DEVICE_RANK in off.disclosure

    on = APDC.custom_family_context(res, farm_dir=tmp_path / "farm")
    assert on.primary_policy == APDC.PRIMARY_BY_ENTRY_LIB
    assert Path(on.model_lib).resolve() == shim.resolve(), (
        "the farm branch loads the resolver's ENTRY lib (spice_libs[0]) — that "
        "is the whole of the second strategy")
    assert APDC.PRIMARY_BY_ENTRY_LIB in on.disclosure

    # the two policies are not the same function here, which is the point
    assert Path(off.model_lib).resolve() != Path(on.model_lib).resolve()

    # the open-PDK path elects nothing at all, and says so
    assert APDC.resolve_deck_context("sky130").primary_policy == \
        APDC.PRIMARY_BY_KNOWN_TABLE


def test_the_sweep_result_carries_the_electing_strategy():
    """The context knowing its own policy is only half of it — the SWEEP RESULT
    is the artefact a reviewer actually reads, and one that records the elected
    lib path but not the policy that chose it still cannot say which world it
    ran in.

    AST over the result dict literal (the emitting function needs a container,
    so it cannot be called here) — the key must survive as a real dict entry,
    not merely appear somewhere in the file.
    """
    src = (PROGS / "analog_real_corner_sweep.py").read_text(errors="replace")
    fn = next((n for n in ast.walk(ast.parse(src))
               if isinstance(n, ast.FunctionDef) and n.name == "run_block"), None)
    assert fn is not None, "run_block was renamed — re-point this check"

    keys = {k.value for d in ast.walk(fn) if isinstance(d, ast.Dict)
            for k in d.keys if isinstance(k, ast.Constant)
            and isinstance(k.value, str)}
    assert "pdk_model_lib_resolved" in keys, (
        "vacuous: the lib-path key this check is anchored to is gone, so its "
        "absence proves nothing about the policy key")
    assert "pdk_primary_policy" in keys, (
        "the sweep result records WHICH lib was elected but no longer WHICH "
        "STRATEGY elected it — vibe-ic#193's two live policies become "
        "indistinguishable in the artefact again")


# --------------------------------------------------------------- the census
def _corpus(tmp_path):
    """Every custom-PDK configuration shape this repo TRACKS, as (label, res,
    reader). There is no PDK checked into the repo and none installed on a CI
    host, so the tracked corpus IS the test tree's fixtures: the staged-lib
    space of this file and `test_analog_pdk_lib_include_farm` (co-located /
    split x self-contained / needs-a-param x either staging order, plus the
    extra-lib variants), the `#149` two-lib and single-lib shapes from
    `test_issue148_151_native_pdk_batch`, and the rung-2 container-installed
    shape from `test_native_installed_corner_lib_include`.

    Synthetic and chip-AGNOSTIC throughout — no vendor / SKU / PDK literal.
    """
    out = []
    n = 0
    for split in (True, False):
        for sc in (True, False):
            for df in (False, True):
                n += 1
                res, _s, _d = _stage(tmp_path / f"c{n:02d}", split=split,
                                     self_contained=sc, device_first=df)
                out.append((f"staged split={split} self_contained={sc} "
                            f"device_first={df}", res, _reader))

    res, _shim, dev = _stage(tmp_path / "missing", split=True,
                             self_contained=True)
    res["spice_libs"] = res["spice_libs"][:1]
    dev.unlink()
    out.append(("split, device lib NOT staged", res, _reader))

    res, _shim, dev = _stage(tmp_path / "decoy", split=True, self_contained=True)
    alt = tmp_path / "decoy" / "models_alt"
    alt.mkdir(parents=True)
    (alt / dev.name).write_text(_device_lib())
    res["spice_libs"].append(str(alt / dev.name))
    out.append(("split + a remote basename decoy", res, _reader))

    res, shim, dev = _stage(tmp_path / "local", split=True, self_contained=True)
    (shim.parent / dev.name).write_text(_device_lib())
    res["spice_libs"].append(str(shim.parent / dev.name))
    out.append(("split + a co-located namesake", res, _reader))

    res, _shim, dev = _stage(tmp_path / "mc", split=True, self_contained=True)
    mcd = tmp_path / "mc" / "mc"
    mcd.mkdir(parents=True)
    (mcd / "mfx180_mc.lib").write_text(_shim_lib(dev.name))
    res["spice_libs"].append(str(mcd / "mfx180_mc.lib"))
    out.append(("split + a second root", res, _reader))

    # in-memory shapes (paths only, never touched on disk)
    la, lb = "/stage/pdk/spice/devices.lib", "/stage/pdk/spice/corners.lib"
    t = {la: (".subckt nch_dev d g s b\n.ends\n.subckt pch_dev d g s b\n"
              ".ends\n.lib tt\n"), lb: ".lib tt\n.lib ss\n.lib ff\n"}
    out.append(("device lib + a more-sections corner lib",
                {"available": True, "source": "project_custom_pdk",
                 "family": "synthfab", "spice_libs": [la, lb]}, t.get))

    solo = "/stage/pdk/spice/all.lib"
    t2 = {solo: (".subckt nch_dev d g s b\n.ends\n.subckt pch_dev d g s b\n"
                 ".ends\n.lib tt\n.lib ss\n")}
    out.append(("a single staged lib",
                {"available": True, "source": "project_custom_pdk",
                 "family": "synthfab", "spice_libs": [solo]}, t2.get))

    a2, b2 = "/stage/pdk/spice/a.lib", "/stage/pdk/spice/b.lib"
    t3 = {a2: ".lib tt\n", b2: ".lib tt\n.lib ss\n.lib ff\n"}
    out.append(("no device role resolves at all",
                {"available": True, "source": "project_custom_pdk",
                 "family": "synthfab", "spice_libs": [a2, b2]}, t3.get))

    m = "/pdks/acme-x1/libs.tech/ngspice/models"
    cl, dl, al = f"{m}/cornermos.lib", f"{m}/devices.lib", f"{m}/aux.lib"
    t4 = {cl: "".join(f".LIB proc_{c}\n.include devices.lib\n.ENDL proc_{c}\n"
                      for c in ("tt", "ss", "ff", "sf", "fs")),
          dl: (".subckt acme_lv_nmos d g s b w=1 l=1\n.ends\n"
               ".subckt acme_lv_pmos d g s b w=1 l=1\n.ends\n"),
          al: ".LIB aux_tt\n.ENDL aux_tt\n"}
    out.append(("rung-2 container-installed, model libs sorted",
                {"available": True, "source": "container_installed",
                 "family": "acmex1", "spice_libs": sorted([al, cl, dl]),
                 "spice_lib": sorted([al, cl, dl])[0]}, t4.get))

    # the rung-1 single-staged-lib shape (test_analog_pdk_deck_context)
    solo1 = "/pdk/myfoundry_x180.lib"
    t5 = {solo1: _device_lib()}
    out.append(("rung-1, one staged custom lib",
                {"available": True, "source": "project_custom_pdk",
                 "family": "myfoundryx180", "spice_libs": [solo1],
                 "spice_lib": solo1}, t5.get))
    return out


def test_the_two_strategies_disagree_on_the_tracked_corpus(tmp_path):
    """HOW BIG is the divergence? A divergence that never changes an outcome is
    a different problem from one that does — so it is counted, with the
    denominator stated.

    MEASURED on this tree: the device-defining rank and `spice_libs[0]` elect a
    DIFFERENT primary library in 8 of the 17 tracked configurations. It is
    therefore not an argument about an edge case; it changes the elected lib in
    just under half of every arrangement the repo knows how to build.

    The counts are asserted exactly. If a future change moves the footprint —
    in EITHER direction — this goes red and the new number has to be stated
    here deliberately. It endorses neither policy.
    """
    corpus = _corpus(tmp_path)
    disagree = []
    for label, res, rdr in corpus:
        head = APDC.custom_family_context(res, reader=rdr).model_lib
        first = (res.get("spice_libs") or [None])[0]
        if head != first:
            disagree.append(label)

    assert len(corpus) == 17, (
        f"the census denominator moved to {len(corpus)}; state the new one")
    assert len(disagree) == 8, (
        f"the two strategies now disagree on {len(disagree)} of {len(corpus)} "
        f"tracked configurations, not 8. Re-state the footprint here "
        f"deliberately.\n" + "\n".join(f"  - {d}" for d in disagree))


def test_the_first_staged_lib_can_be_a_lib_that_defines_no_device(tmp_path):
    """The single most consequential row of the census, pinned on its own,
    because it is the one shape that comes from a REAL resolver rather than a
    hand-staged fixture.

    Rung-2 (container-installed) lists every model lib under the PDK's ngspice
    dir SORTED BY NAME, so `spice_libs[0]` is whichever file sorts first — here
    an auxiliary corner lib that defines ZERO devices. Electing it would emit a
    deck whose `.lib` line loads a section with no `nmos`/`pmos` in it at all.

    That is a consequence, not a verdict: it says what adopting the first-staged
    policy would DO on this shape, and leaves the choice where it belongs.
    """
    m = "/pdks/acme-x1/libs.tech/ngspice/models"
    cl, dl, al = f"{m}/cornermos.lib", f"{m}/devices.lib", f"{m}/aux.lib"
    texts = {cl: "".join(f".LIB proc_{c}\n.include devices.lib\n.ENDL proc_{c}\n"
                         for c in ("tt", "ss", "ff")),
             dl: (".subckt acme_lv_nmos d g s b w=1 l=1\n.ends\n"
                  ".subckt acme_lv_pmos d g s b w=1 l=1\n.ends\n"),
             al: ".LIB aux_tt\n.ENDL aux_tt\n"}
    libs = sorted([al, cl, dl])
    assert libs[0] == al, "the sort that makes the aux lib first-staged"

    res = {"available": True, "source": "container_installed",
           "family": "acmex1", "spice_libs": libs, "spice_lib": libs[0]}
    ctx = APDC.custom_family_context(res, reader=texts.get)

    assert ctx.model_lib == cl and ctx.status == "OK"
    assert ctx.device_map == {"nmos": "acme_lv_nmos", "pmos": "acme_lv_pmos"}
    # and the alternative, stated as a measurement of the SAME fixture
    assert APDC.transitive_subckts(al, texts[al], texts.get) == {}, (
        "spice_libs[0] on this shape reaches no device subckt at all")
