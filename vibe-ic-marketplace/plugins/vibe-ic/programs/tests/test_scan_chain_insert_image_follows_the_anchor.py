"""`fault_scan_chain_insert` must not own an image pointer of its own.

WHY THIS EXISTS
    A module-level `DEFAULT_IMAGE = "ghcr.io/vibeic/vibeic-eda:0.2.x"` does not
    fail loudly. It FREEZES: the code keeps running one toolchain while
    everything around it moves, and every gate reports green. This module is a
    likely place for one, because its two ghcr tags sit inside `MEASURED (...)`
    comment blocks that quote a tool's verbatim stdout beside the tag that
    produced it — so a reader scanning for pointers sees tags here and may
    conclude the module owns one.

    It does not. It runs whatever `fault_atpg_run` resolves, and
    `fault_atpg_run` asks `_eda_image.resolve()`.

    WHAT CHANGED. This used to be phrased as an exemption from
    `sync_image_version.py --check`, a repo-root drift net keyed on
    `tools/vibeic-eda/VERSION`. Both are deleted: that file held vibeic-eda's
    version number inside the vibe-ic repo, so every image release needed a PR
    here. The RULE did not change and is now held by
    `test_the_eda_image_is_resolved_not_remembered
    ::test_no_module_level_constant_freezes_an_image_version`, which ships with
    the plugin instead of running only in this repo's CI.

    These tests assert on VALUES the modules actually expose at runtime — the
    resolved image string and the module namespace — never on source text, so
    they cannot be satisfied by moving a comment around.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

import fault_atpg_run as far
import fault_scan_chain_insert as fsci

_PROGRAMS = Path(far.__file__).resolve().parent
_REPO = _PROGRAMS.parents[3]

_GHCR = re.compile(r"^ghcr\.io/vibeic/vibeic-eda:\d+\.\d+\.\d+$")


def test_this_repo_stores_no_vibeic_eda_version():
    """A guard on this file's own premise. If an anchor file comes back, the
    module below can start reading it again and everything here still passes."""
    assert not (_REPO / "tools" / "vibeic-eda" / "VERSION").exists(), (
        "the anchor is back; every vibeic-eda release now needs a PR here again")


def test_a_total_blackout_answers_the_legacy_image_AND_SAYS_SO(monkeypatch, capsys):
    """With no env override and NOTHING reachable — no registry, no local fork
    image — the resolver falls back to upstream iic-osic-tools, which has neither
    Fault nor the patched yosys. That is a real degradation, so the rule is not
    "never answer a floating tag" (there is nothing else left to answer); it is
    NEVER SILENTLY. A toolchain quietly older, or quietly missing tools, than the
    caller believes it is running is the failure this resolution order exists to
    prevent, and the announcement is the only thing standing between a DFT step
    and a silently unforked yosys."""
    monkeypatch.delenv("VIBEIC_EDA_IMAGE", raising=False)
    monkeypatch.delenv("IIC_EDA_IMAGE", raising=False)

    def _never_present(*a, **k):
        raise OSError("no docker in this test")

    # A module reaches a process through `subprocess`, through `_pr`
    # (`_progress_run`, the progress-supervised drop-in) or through both.
    # Substituting on only one leaves the real launcher answering the
    # question this test is asking about a fake one, and the test then
    # passes or fails for a reason that has nothing to do with its subject.
    import _progress_run as _pr                                # noqa: PLC0415
    # `_eda_image` is a DIFFERENT module and resolves the daemon through the
    # shared `_progress_run`, so substituting only on `far`'s own launcher
    # leaves the real daemon answering the blackout this test is staging.
    for _launcher in (getattr(far, "subprocess", None),
                      getattr(far, "_pr", None), _pr):
        if _launcher is not None:
            monkeypatch.setattr(_launcher, "run", _never_present)
            monkeypatch.setattr(_launcher, "run_best_effort", _never_present,
                                raising=False)
    got = far._resolve_docker_image()
    import _eda_image as M
    assert got == M.LEGACY_IMAGE, got
    assert "does NOT carry the forked tools" in capsys.readouterr().err


def test_the_resolver_prefers_a_local_fork_image_over_upstream(monkeypatch):
    """The property the deleted anchor used to carry here. With the registry
    unreachable, a DFT step must not silently drop to upstream iic-osic-tools,
    which has neither Fault nor the patched yosys — it must run a fork image this
    machine already holds."""
    monkeypatch.delenv("VIBEIC_EDA_IMAGE", raising=False)
    monkeypatch.delenv("IIC_EDA_IMAGE", raising=False)
    import _eda_image as M
    monkeypatch.setattr(M, "registry_digest", lambda *a, **k: None)
    monkeypatch.setattr(M, "local_tags", lambda *a, **k: ["0.3.13"])
    assert far._resolve_docker_image() == f"{M.IMAGE_REPO}:0.3.13"


def test_an_explicit_env_image_still_wins(monkeypatch):
    """The escape hatch keeps working — otherwise the assertion above would be
    pinning a constant rather than a resolution order."""
    monkeypatch.setenv("VIBEIC_EDA_IMAGE", "example.invalid/some/image:9.9.9")
    assert far._resolve_docker_image() == "example.invalid/some/image:9.9.9"


def test_scan_chain_module_declares_no_image_of_its_own():
    """Walks the module NAMESPACE (runtime values), not the file text. Any
    module-level string that is a fully-qualified vibeic-eda image reference is a
    pointer that freezes: nothing advances it, and the code keeps pulling one
    toolchain while everything around it moves.
    """
    importlib.reload(fsci)
    offenders = {
        name: val
        for name, val in vars(fsci).items()
        if isinstance(val, str) and _GHCR.match(val.strip())
    }
    assert offenders == {}, (
        f"{Path(fsci.__file__).name} declares {offenders}, which nothing will "
        f"ever advance — this repo stores no vibeic-eda version any more, by "
        f"design. Resolve the image through fault_atpg_run, which asks "
        f"_eda_image.resolve()."
    )


def test_scan_chain_reports_the_image_the_atpg_module_resolved():
    """The value the module would publish in its report is the SAME value the
    registered module resolved — that indirection is what makes the exemption
    cost no live coverage."""
    assert fsci._fatpg is far
    assert fsci._fatpg.DOCKER_IMAGE == far.DOCKER_IMAGE
