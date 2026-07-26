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
     farm exists for — and `build_lib_include_farm` currently has NO production
     caller (see the last test), so the runtime cannot reach the repair.

The container-backed tests SKIP (never fail) when no ngspice is available; the
pure-python ones always run and pin the mechanism.
"""
from __future__ import annotations

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
# FINDING 4 — the repair for case D exists and nothing calls it.
# =====================================================================

def test_include_farm_has_no_production_caller(tmp_path):
    """`build_lib_include_farm` co-locates the include closure, which is the
    ONLY thing that makes case D loadable — and no runtime caller passes
    `farm_dir`, so the runtime cannot reach it.

    This is a DISCLOSURE test, deliberately asserting the CURRENT state: if
    someone wires the farm back in, it fails and gets deleted along with this
    docstring. It is here so 'the farm handles that' cannot be said of a code
    path nothing executes.
    """
    prod_calls = []
    for py in sorted(PROGS.glob("*.py")):
        if py.name == "analog_pdk_deck_context.py":
            continue          # the defining module
        for i, line in enumerate(py.read_text(errors="replace").split("\n"), 1):
            stripped = line.strip()
            if stripped.startswith(("#", "*")) or not stripped:
                continue
            if "build_lib_include_farm(" in line or "farm_dir=" in line:
                prod_calls.append(f"{py.name}:{i}: {stripped[:100]}")

    assert prod_calls == [], (
        "the include farm now HAS a runtime caller — case D may be repairable. "
        "Re-measure test_ngspice_split_and_non_self_contained_neither_"
        "candidate_loads and delete this test with its finding.\n"
        + "\n".join(prod_calls))
    # And it is genuinely functional, not merely absent — so the gap is
    # WIRING, not capability.
    _res, shim, dev = _stage(tmp_path, split=True, self_contained=True)
    farm = APDC.build_lib_include_farm([str(shim), str(dev)],
                                       tmp_path / "farm", roots=[str(shim)])
    assert farm.get("map"), farm
