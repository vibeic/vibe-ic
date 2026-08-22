#!/usr/bin/env python3
"""The plugin asks which EDA image is current; it does not remember a version.

WHAT THIS REPLACES. The image version was a literal in eleven places, kept in
step by `tools/vibeic-eda/sync_image_version.py --check` and advanced by a PR
that vibeic-eda's daily release opened on this repo. The stated reason was that
the pinned tag "matches what the plugin was VERIFIED AGAINST".

Measured 2026-08-20: nothing verified that. The release proved the tag was
PULLABLE and then wrote the verification claim anyway, on every publish — and
charged a cross-repo check-in for it. vibeic-eda is built FOR this plugin and
sits under it; its own release gate proves 78 commands across 17 replaced
prefixes still resolve, runs 439 fork self-checks, and refuses to build unless
sby/yices, ALIGN, klayout and the xyce plugin builder all work.

Three properties are load-bearing here, and each has a way of quietly coming
undone:
  1. no literal version anywhere in the shipped programs — one left behind is
     one that silently freezes while everything else moves;
  2. `resolve()` never answers a bare `:latest` — `docker run …:latest` does not
     consult the registry, so it means "whatever this machine pulled, whenever";
  3. `resolve()` and `local_image()` stay DIFFERENT questions — collapsing them
     hands `docker run` a 6.68 GB fetch across 84 layers where a skip guard
     expected a local check.
"""
from __future__ import annotations

import pathlib
import re
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import _eda_image as M  # noqa: E402

_PINNED = re.compile(r"vibeic-eda:\d+\.\d+\.\d+")


# ── 1. nothing remembers a version ──────────────────────────────────────────

_CONSUMERS = (
    "fault_atpg_run.py",
    "fmeda_fault_injection_coverage.py",
    "sta_engine_parity_check.py",
    "pdk_via_patch_meets_layer_min_width_check.py",
    "tests/test_v1_4_21_dft_atpg_liberty_resolver.py",
    "tests/test_extraction_input_capability_check.py",
)


@pytest.mark.parametrize("rel", _CONSUMERS)
def test_the_image_consumers_carry_no_pinned_version(rel):
    """These six decided which image RUNS. A literal left in one of them does
    not fail loudly — it freezes, and keeps running an older toolchain than
    everything around it."""
    src = (_PROGRAMS / rel).read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    code = re.sub(r'"""(?:.|\n)*?"""', "", code)
    assert not _PINNED.search(code), f"{rel} still pins a version"
    assert "_eda_image" in src, f"{rel} does not ask _eda_image"


def test_no_module_level_constant_freezes_an_image_version():
    """The shape that goes stale silently, stated as a shape rather than a list
    of files — a NEW `DEFAULT_IMAGE = "...:0.3.16"` is caught by the same test.

    Deliberately NOT a sweep for the string anywhere, and deliberately not
    over tests: this tree is full of honest history (`MEASURED ... image
    vibeic-eda:0.2.30`) and fixture constants (`PINNED = "…:9.9.9"`), and a
    guard that fires on those gets deleted by the next person who trips over
    it — which leaves the real rule unguarded."""
    import ast

    offenders = []
    for path in sorted(_PROGRAMS.rglob("*.py")):
        # SHIPPED programs only. A test may legitimately define a fixture
        # constant (`PINNED = "…:9.9.9"`); a program that runs the toolchain
        # may not, because that one decides which image actually runs.
        if "tests" in path.relative_to(_PROGRAMS).parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in tree.body:                       # module level only
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str) \
                    and _PINNED.search(value.value):
                offenders.append(f"{path.relative_to(_PROGRAMS).as_posix()}:{node.lineno}")
    assert not offenders, (
        "module-level constants pinning an image version — ask _eda_image "
        f"instead: {offenders}")


# ── 2. never a bare :latest ─────────────────────────────────────────────────

def test_resolve_returns_a_digest_not_a_floating_tag(monkeypatch):
    monkeypatch.setattr(M, "registry_digest", lambda *a, **k: "sha256:" + "a" * 64)
    got = M.resolve(env={})
    assert got == f"{M.IMAGE_REPO}@sha256:{'a' * 64}"
    assert ":latest" not in got


def test_an_unreachable_registry_says_so_instead_of_pretending(monkeypatch, capsys):
    """The fallback is honest, not silent: a toolchain quietly older than the
    caller believes is the failure this module exists to prevent."""
    monkeypatch.setattr(M, "registry_digest", lambda *a, **k: None)
    monkeypatch.setattr(M, "local_tags", lambda *a, **k: ["0.3.9", "0.3.10"])
    got = M.resolve(env={})
    assert got == f"{M.IMAGE_REPO}:0.3.9"      # first of the list as given
    assert "registry unreachable" in capsys.readouterr().err


def test_an_offline_run_still_prefers_the_anchor_over_upstream(monkeypatch, capsys):
    """A REGRESSION I SHIPPED, caught by
    `test_scan_chain_insert_image_follows_the_anchor`. Dropping straight to the
    legacy image when the registry is unreachable hands a DFT step a toolchain
    with no Fault and no patched yosys. Being unable to ASK which image is
    current is not a reason to forget which one this tree names."""
    monkeypatch.setattr(M, "registry_digest", lambda *a, **k: None)
    monkeypatch.setattr(M, "local_tags", lambda *a, **k: [])
    monkeypatch.setattr(M, "anchor_image",
                        lambda *a, **k: f"{M.IMAGE_REPO}:0.3.16")
    got = M.resolve(env={})
    assert got == f"{M.IMAGE_REPO}:0.3.16"
    assert "using the anchor this checkout names" in capsys.readouterr().err


def test_with_nothing_at_all_it_names_the_legacy_image_and_warns(monkeypatch, capsys):
    """Only when there is no registry, no local image AND no anchor."""
    monkeypatch.setattr(M, "registry_digest", lambda *a, **k: None)
    monkeypatch.setattr(M, "local_tags", lambda *a, **k: [])
    monkeypatch.setattr(M, "anchor_image", lambda *a, **k: None)
    got = M.resolve(env={})
    assert got == M.LEGACY_IMAGE
    assert "does NOT carry the forked tools" in capsys.readouterr().err


@pytest.mark.parametrize("key", ["VIBEIC_EDA_IMAGE", "IIC_EDA_IMAGE"])
def test_an_explicit_override_wins_over_everything(monkeypatch, key):
    monkeypatch.setattr(M, "registry_digest",
                        lambda *a, **k: pytest.fail("must not ask the registry"))
    assert M.resolve(env={key: "my/own:image"}) == "my/own:image"


# ── 3. the two questions stay apart ─────────────────────────────────────────

def test_local_image_never_touches_the_registry(monkeypatch):
    """Collapsing this into `resolve` turns a skip guard's local check into an
    unbounded pull."""
    monkeypatch.setattr(M, "registry_digest",
                        lambda *a, **k: pytest.fail("local_image asked the registry"))
    monkeypatch.setattr(M, "local_tags", lambda *a, **k: ["0.3.16"])
    assert M.local_image(env={}) == f"{M.IMAGE_REPO}:0.3.16"


def test_local_image_is_None_when_the_machine_has_nothing(monkeypatch):
    monkeypatch.setattr(M, "local_tags", lambda *a, **k: [])
    monkeypatch.setattr(M, "_run", lambda *a, **k: type("R", (), {"returncode": 1})())
    assert M.local_image(env={}) is None


def test_local_tags_are_newest_first_and_ignore_non_semver(monkeypatch):
    out = type("R", (), {"returncode": 0,
                         "stdout": "latest\n0.3.9\n0.3.10\nedge\n0.4.0\n"})()
    monkeypatch.setattr(M, "_run", lambda *a, **k: out)
    assert M.local_tags() == ["0.4.0", "0.3.10", "0.3.9"]


# ── 4. running a tool and judging one are different questions ───────────────
#
# THE ONE I GOT WRONG. The first cut of this change sent all six consumers to
# `resolve()`, which asks the registry. That is right for running a tool and
# wrong for a gate that reports FAIL about the image's CONTENTS: a third
# party's push would then change a blocking verdict with no commit in this
# tree. vibe-ic#927 had already written that down —
#
#     falling back to the floating tag would let a third party's push change
#     this BLOCKING gate's verdict
#
# — in `pdk_registry_selectable_check`, which is why that program reads
# `tools/vibeic-eda/VERSION` and returns None rather than falling back.
# The question I failed to ask was not "where is a version pinned" but "is this
# version used to RUN something or to JUDGE something".

_VERDICT_BEARING = (
    "sta_engine_parity_check.py",                    # FAILs about the engines IN the image
    "pdk_via_patch_meets_layer_min_width_check.py",  # FAILs about tech LEFs read FROM it
)
_TOOL_RUNNING = (
    "fault_atpg_run.py",
    "fmeda_fault_injection_coverage.py",
)


@pytest.mark.parametrize("rel", _VERDICT_BEARING)
def test_a_gate_that_judges_the_image_uses_this_checkouts_anchor(rel):
    src = (_PROGRAMS / rel).read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    assert "anchor_image" in code, (
        f"{rel} reports a verdict about the image, so it must ask "
        "_eda_image.anchor_image() — what THIS CHECKOUT names")
    assert "_img.resolve()" not in code, (
        f"{rel} asks the registry. Its verdict would then change whenever "
        "anyone publishes an image, with no commit here (vibe-ic#927)")


@pytest.mark.parametrize("rel", _TOOL_RUNNING)
def test_a_program_that_runs_the_toolchain_takes_the_current_image(rel):
    """The other half. Pinning these would put them back on a version that only
    moves when somebody remembers to move it — the thing this change removed."""
    src = (_PROGRAMS / rel).read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    assert "_img.resolve()" in code, f"{rel} should take the current image"


def test_the_anchor_refuses_to_invent_an_answer(monkeypatch, tmp_path):
    """No VERSION and no override is None — NOT a floating tag. Returning one
    would hand a blocking gate a verdict somebody else can move."""
    monkeypatch.setattr(M.os.path, "isfile", lambda _p: False)
    assert M.anchor_image(env={}) is None


def test_a_mutable_override_is_announced_not_silently_accepted(monkeypatch, capsys):
    monkeypatch.setattr(M.os.path, "isfile", lambda _p: False)
    assert M.anchor_image(env={"VIBEIC_EDA_IMAGE": "ghcr.io/x/y:latest"}) \
        == "ghcr.io/x/y:latest"
    assert "floating reference" in capsys.readouterr().err


@pytest.mark.parametrize("ref", [
    "ghcr.io/vibeic/vibeic-eda:0.3.16",
    "ghcr.io/vibeic/vibeic-eda@sha256:" + "b" * 64,
])
def test_an_immutable_override_passes_without_a_warning(monkeypatch, capsys, ref):
    monkeypatch.setattr(M.os.path, "isfile", lambda _p: False)
    assert M.anchor_image(env={"VIBEIC_EDA_IMAGE": ref}) == ref
    assert capsys.readouterr().err == ""


# ── 5. the refusal must exit the program's OWN "cannot check" code ───────────
#
# The two judging programs refuse when `anchor_image()` answers None. That
# refusal first shipped as `raise SystemExit("<message>")`, and a SystemExit
# carrying a STRING exits 1 — which is not a neutral number in either file:
#
#   sta_engine_parity_check          RC_AGREE, RC_DISAGREE, RC_CANNOT_CHECK = 0, 1, 2
#   pdk_via_patch_..._width_check    1 = a via patch narrower than its layer's
#                                        declared minimum; 2 = [REFUSE]
#
# So a run that never opened an image reported "the STA engines disagree" and "a
# via patch is too narrow". MEASURED from a copy of `programs/` with no repo
# root above it — which is exactly how the plugin is INSTALLED, because
# `tools/vibeic-eda/VERSION` lives ABOVE the plugin directory and does not ship
# inside it. Every end user would have read a hard finding about silicon from a
# run that measured nothing.
#
# This is the repository's own rule, in the direction that invents a defect
# rather than hiding one: "I could not read it" and "I read it and it was bad"
# must never produce the same verdict.

import os          # noqa: E402
import shutil      # noqa: E402
import subprocess  # noqa: E402

_REFUSERS = (
    # program                                     the code that means "cannot check"
    ("sta_engine_parity_check.py",                 2, ()),
    ("pdk_via_patch_meets_layer_min_width_check.py", 2, ("--from-image",)),
)


@pytest.mark.parametrize("prog,cannot_check_rc,argv", _REFUSERS)
def test_the_anchor_refusal_exits_cannot_check_not_a_finding(
        prog, cannot_check_rc, argv, tmp_path):
    """Run it the way an INSTALLED plugin runs it: `programs/` with no repo root.

    Copying the directory is the point of the test. Inside this checkout
    `anchor_image()` finds `tools/vibeic-eda/VERSION` and the refusal path never
    executes, so a test that ran in place would assert nothing.
    """
    staged = tmp_path / "programs"
    shutil.copytree(_PROGRAMS, staged,
                    ignore=shutil.ignore_patterns("tests", "__pycache__"))
    assert not list(staged.rglob("vibeic-eda/VERSION")), (
        "the fixture accidentally carries an anchor, so the refusal path is "
        "not reachable and this test would prove nothing")

    env = {k: v for k, v in os.environ.items()
           if k not in ("VIBEIC_EDA_IMAGE", "IIC_EDA_IMAGE")}
    r = subprocess.run([sys.executable, str(staged / prog), *argv],
                       capture_output=True, text=True, env=env, timeout=120)

    assert r.returncode == cannot_check_rc, (
        f"{prog} refused with rc={r.returncode}; {cannot_check_rc} is its word "
        f"for 'nothing was measured' and rc=1 is a FINDING about the design. "
        f"stderr: {r.stderr[-400:]}")
    assert ("[CANNOT CHECK]" in r.stderr or "[REFUSE]" in r.stderr), (
        f"{prog} exited {cannot_check_rc} without saying it could not look; a "
        f"silent 2 is indistinguishable from a skip. stderr: {r.stderr[-400:]}")
