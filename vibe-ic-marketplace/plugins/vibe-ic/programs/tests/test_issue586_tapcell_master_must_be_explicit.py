"""#586 — the tapless-PDK carve-out's own signal could be produced by omission.

The issue asked for a `tapless_pdk` carve-out in the step-28 well-tap rule so a
PDK with no tapcell master stops reporting a conclusive latch-up FAIL. That
carve-out is already there (v1.3.94 geometry verification, v1.6.89 signal), with
all four branches and a runner-level test covering both directions. What was NOT
there is any guarantee that the signal means what it says.

THE SIGNAL IS `pdk.tapcell_master is None`, AND None HAS TWO SOURCES

    reg.get("tapcell_master")     # an OMITTED key -> None
    "tapcell_master": null        # a STATED tapless PDK -> None

They are indistinguishable, and the issue itself names the direction this makes
dangerous:

    "It must not become a PASS. … Converting a false conclusive FAIL into a
     false PASS on a latch-up gate would be strictly worse than today."

An omitted key does exactly that: the latch-up gate takes the tapless path, the
geometry measurement cannot run without `tap_geom_layers`, and a genuinely
skipped tapcell step lands as MANUAL_REVIEW / WELLTAP_TAPLESS_INDETERMINATE —
non-blocking — instead of the conclusive FAIL it is.

FOUND LIVE ON `asap7`, not hypothetically. Its `_detect_pdk` branch builds a
PdkConfig from the registry entry and never passes the field, and the entry
never carried it, so `--pdk asap7` resolved to `tapcell_master=None`. Measured
in `ghcr.io/vibeic/vibeic-eda:0.2.51`:

    MACRO TAPCELL_ASAP7_75t_R
      CLASS CORE WELLTAP ;
      SIZE 0.108 BY 0.27 ;
      SITE asap7sc7p5t ;        <- the site the registry entry declares

so ASAP7 is a tapcell-methodology PDK whose tapcell step was self-skipping. The
same omission sat on `sky130A` and `nangate45`; both are shadowed by hard-coded
named branches that supply the master, so they were latent rather than live —
and latent only for as long as those branches exist.

THE FIX IS THAT "TAPLESS" HAS TO BE SAID. Every selectable entry declares the
key; `pdk_registry_selectable_check` fails one that omits it. `ihp-sg13g2` keeps
its null, which now carries the meaning it always claimed.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys

import pytest
# vibe-ic#1128 — these skips mean A VERIFICATION DID NOT HAPPEN, not that
# one passed. Declared through `not_verified_tier` so the run's roll-up
# cannot count them under `passed`; see that module's docstring.
from not_verified_tier import skip_not_verified  # noqa: E402
PULL_REMEDY = 'docker pull ghcr.io/vibeic/vibeic-eda:latest'  # the repo stores no version to cat
RUN_REMEDY = 'bash tools/vibeic-eda/restart-eda.sh'

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
_REGISTRY = _PROGRAMS / "pdk_registry.json"
_GATE = _PROGRAMS / "pdk_registry_selectable_check.py"

REG = json.loads(_REGISTRY.read_text(encoding="utf-8"))
ENTRIES = [e for e in REG["pdks"] if isinstance(e, dict)]
#: Entries that name a directory in the image. `custom_auto_detect` is the
#: auto-detect sentinel, not a PDK, and the gate exempts it the same way.
SELECTABLE = [e for e in ENTRIES if e.get("name") and e.get("container_path")]


# ── the invariant, as data ───────────────────────────────────────────────────
@pytest.mark.parametrize("entry", SELECTABLE, ids=lambda e: e["name"])
def test_every_selectable_entry_states_its_tapcell_master(entry):
    """Present as a key. Its VALUE may be null — that is the tapless statement —
    but the key has to be there, because absence is read as that statement."""
    assert "tapcell_master" in entry, (
        f"{entry['name']} omits `tapcell_master`; the resolver cannot tell that "
        f"from an explicit null, which sends the latch-up gate down the "
        f"tapless-cell path")


def test_the_one_null_is_a_stated_null():
    """ihp-sg13g2 is genuinely tapless. The point of this file is that its null
    is now DISTINGUISHABLE from an omission, not that nulls are forbidden."""
    ihp = next(e for e in ENTRIES if e["name"] == "ihp-sg13g2")
    assert "tapcell_master" in ihp and ihp["tapcell_master"] is None
    assert ihp.get("tap_geom_layers"), (
        "a stated-tapless PDK needs tap_geom_layers for the geometry check to "
        "produce POSITIVE evidence; without it the carve-out can only return "
        "INDETERMINATE and the null buys nothing")


# ── the gate blocks on an omission ───────────────────────────────────────────
def _run_gate(registry_path):
    """The NAME half only, which is the half this invariant lives in.

    `VIBEIC_EDA_IMAGE` is pointed at a tag that cannot resolve, so the gate's
    asset half reports SKIPPED instead of shelling into docker. That is not a
    convenience: with the image reachable this call took minutes, and a test
    whose inner bound outlives the 180s harness kills the SESSION rather than
    failing. Measured at 0.06s image-free, so 30s is a ceiling, not a budget.
    """
    env = dict(os.environ, VIBEIC_EDA_IMAGE="ghcr.io/vibeic/no-such-image:0")
    return subprocess.run(
        [sys.executable, str(_GATE), "--registry", str(registry_path),
         "--container", "__no_such_container__"],
        capture_output=True, text=True, timeout=30, env=env)


def test_the_gate_passes_on_the_shipped_registry():
    r = _run_gate(_REGISTRY)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("victim", ["asap7", "sky130A", "ihp-sg13g2"])
def test_the_gate_fails_when_a_declaration_is_removed(tmp_path, victim):
    """Proven negative, per entry — including the tapless one, whose null is a
    declaration like any other. A gate that only noticed the entry I happened to
    fix would be a gate against one commit."""
    d = json.loads(_REGISTRY.read_text(encoding="utf-8"))
    for e in d["pdks"]:
        if e.get("name") == victim:
            e.pop("tapcell_master")
    f = tmp_path / "reg.json"
    f.write_text(json.dumps(d, indent=2), encoding="utf-8")
    r = _run_gate(f)
    assert r.returncode == 1, r.stdout + r.stderr
    assert victim in r.stdout, r.stdout


def test_an_entry_without_a_container_path_is_exempt(tmp_path):
    """The sentinel must not be forced to declare physical cells it has none of.
    Without this the gate would fail on a correct registry, and a gate that
    fails on correct input gets routed around.

    ADDED to the shipped registry rather than filtering it down to the sentinel:
    a registry with no container_path at all makes every shipped tree read as
    unregistered, which fails on a DIFFERENT finding and would have passed this
    test for the wrong reason once the exemption broke.
    """
    d = json.loads(_REGISTRY.read_text(encoding="utf-8"))
    d["pdks"].append({"name": "another_sentinel", "process_node_nm": 0,
                      "open_source": True})
    f = tmp_path / "reg.json"
    f.write_text(json.dumps(d, indent=2), encoding="utf-8")
    r = _run_gate(f)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "another_sentinel" not in r.stdout, r.stdout


# ── the registry and the hard-coded branches must not drift ──────────────────
_BRANCH_SRC = (_PROGRAMS / "phase3_one_shot_runner.py").read_text(encoding="utf-8")


def _branch_tapcell(name):
    """The literal a named branch passes, or None if it passes none.

    Read from source because these branches need a container to execute. The
    weakness is real and the test below is scoped to it: it compares two
    declarations, so a drift between them fails even though neither side is
    executed here.
    """
    i = _BRANCH_SRC.find(f'name="{name}"')
    if i == -1:
        return "<no branch>"
    seg = _BRANCH_SRC[i:i + 4000]
    m = re.search(r'tapcell_master=("([^"]*)"|None|reg\.get\("tapcell_master"\))',
                  seg)
    return m.group(1) if m else None


@pytest.mark.parametrize("name", ["sky130A", "nangate45"])
def test_a_hardcoded_branch_matches_its_registry_entry(name):
    """These two supply the master themselves. If the two declarations disagree,
    the registry is documentation that lies — and the gate above enforces the
    registry, so the lie is what future readers get."""
    entry = next(e for e in ENTRIES if e["name"] == name)
    assert _branch_tapcell(name) == f'"{entry["tapcell_master"]}"', (
        f"{name}: branch says {_branch_tapcell(name)}, registry says "
        f"{entry['tapcell_master']!r}")


def test_the_asap7_branch_reads_the_registry_rather_than_hardcoding():
    """The live defect: this branch built a PdkConfig without the field at all.

    COMMENTS STRIPPED — the fix's comment names the field to explain why it is
    now passed, and a scan that cannot tell documentation from code has to be
    weakened the first time someone documents something.
    """
    code = "\n".join(ln for ln in _BRANCH_SRC.splitlines()
                     if not ln.lstrip().startswith("#"))
    i = code.find('name="asap7"')
    assert i != -1, "the asap7 branch moved"
    assert 'tapcell_master=reg.get("tapcell_master")' in code[i:i + 4000], (
        "the asap7 branch does not carry tapcell_master, so it resolves to "
        "None and asap7 is treated as a tapless-cell PDK again")


# ── the value is a real cell, verified in the image ──────────────────────────
def _image():
    """The image this host holds, BY DIGEST — asked, not remembered.

    This used to walk up for `tools/vibeic-eda/VERSION`, vibeic-eda's version
    number stored in the vibe-ic repo, which made every image release need a PR
    here. `_eda_image.judged_image()` honours the same `VIBEIC_EDA_IMAGE`
    override and answers None the same way when there is nothing to look at.
    """
    sys.path.insert(0, str(_PROGRAMS))
    import _eda_image as _img
    return _img.judged_image().ref


def _have_image(img):
    return bool(img) and subprocess.run(
        ["docker", "image", "inspect", img],
        capture_output=True, text=True).returncode == 0


@pytest.mark.parametrize(
    "entry", [e for e in SELECTABLE if e.get("tapcell_master")],
    ids=lambda e: e["name"])
def test_the_declared_master_exists_in_that_pdks_own_lef(entry):
    """A declaration the library does not contain is an unplaceable master, and
    the tapcell step would die at PnR instead of at registry review.

    Image-gated and SKIPPED without one — never folded into a pass, because
    "I could not look" and "I looked and it is there" are different claims.
    """
    img = _image()
    if not _have_image(img):
        skip_not_verified(
            f"image {img} not present; this half was NOT checked",
            PULL_REMEDY)
    cell = entry["tapcell_master"]
    r = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "bash", img, "-lc",
         f"grep -rl 'MACRO {cell}' {entry['container_path']} 2>/dev/null | head -1"],
        capture_output=True, text=True, timeout=60)
    assert r.stdout.strip(), (
        f"{entry['name']} declares tapcell_master={cell!r}, which is not a "
        f"MACRO anywhere under {entry['container_path']}")
