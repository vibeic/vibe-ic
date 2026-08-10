"""`fault_scan_chain_insert` must not own an image pointer of its own.

WHY THIS EXISTS
    `sync_image_version.py --check` flags any fully-qualified
    `ghcr.io/vibeic/vibeic-eda:X.Y.Z` outside the registered install docs,
    because an unregistered LIVE pointer is invisible in exactly the direction
    that matters: the drift gate passes while the code keeps pulling an old
    image. `fault_scan_chain_insert.py` tripped that net at 0.2.65 while the
    anchor was 0.2.75.

    That hit was a FALSE POSITIVE, and the file is now listed in
    `.image-version-ignore`: both of its ghcr tags sit inside `MEASURED (...)`
    comment blocks that quote a tool's verbatim stdout beside the tag that
    produced it, so advancing them would attribute those exact lines to an
    image that never emitted them.

    An exemption is only as good as its premise. The premise here is that the
    module names NO image itself — it runs whatever `fault_atpg_run` resolves,
    and `fault_atpg_run.py` IS a registered install-doc candidate whose
    pointers the anchor rewrites. If someone later writes a
    `DEFAULT_IMAGE = "ghcr.io/vibeic/vibeic-eda:0.2.x"` into the exempted
    module, the drift net will stay silent about it FOREVER, and the code
    would pull a pinned stale image while every gate reported green.

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
_VERSION_FILE = _REPO / "tools" / "vibeic-eda" / "VERSION"

_GHCR = re.compile(r"^ghcr\.io/vibeic/vibeic-eda:\d+\.\d+\.\d+$")


def _anchor() -> str:
    return _VERSION_FILE.read_text(encoding="utf-8").strip()


def test_the_anchor_file_is_where_we_think_it_is():
    # A guard on this test's own premise: if the VERSION file moves, the
    # assertions below would silently compare against nothing.
    assert _VERSION_FILE.is_file(), f"no VERSION file at {_VERSION_FILE}"
    assert re.fullmatch(r"\d+\.\d+\.\d+", _anchor()), _anchor()


def test_resolver_falls_back_to_the_anchor_version(monkeypatch):
    """With no env override and nothing available locally, the image the DFT
    steps pull is the ANCHOR image — asserted on the returned string."""
    monkeypatch.delenv("VIBEIC_EDA_IMAGE", raising=False)
    monkeypatch.delenv("IIC_EDA_IMAGE", raising=False)

    def _never_present(*a, **k):
        raise OSError("no docker in this test")

    monkeypatch.setattr(far.subprocess, "run", _never_present)
    assert far._resolve_docker_image() == f"ghcr.io/vibeic/vibeic-eda:{_anchor()}"


def test_an_explicit_env_image_still_wins(monkeypatch):
    """The escape hatch keeps working — otherwise the assertion above would be
    pinning a constant rather than a resolution order."""
    monkeypatch.setenv("VIBEIC_EDA_IMAGE", "example.invalid/some/image:9.9.9")
    assert far._resolve_docker_image() == "example.invalid/some/image:9.9.9"


def test_scan_chain_module_declares_no_image_of_its_own():
    """The premise of the `.image-version-ignore` entry for this module.

    Walks the module NAMESPACE (runtime values), not the file text. Any
    module-level string that is a fully-qualified vibeic-eda image reference
    is a live pointer the drift net can no longer see, because the file is
    exempt — so it must not exist.
    """
    importlib.reload(fsci)
    offenders = {
        name: val
        for name, val in vars(fsci).items()
        if isinstance(val, str) and _GHCR.match(val.strip())
    }
    assert offenders == {}, (
        f"{Path(fsci.__file__).name} is exempt from the image drift net "
        f"(.image-version-ignore) because it was believed to carry no live "
        f"pointer. It now declares {offenders}, which nothing will ever "
        f"advance. Either resolve the image through fault_atpg_run, or "
        f"remove the file from .image-version-ignore and register it in "
        f"INSTALL_DOC_CANDIDATES."
    )


def test_scan_chain_reports_the_image_the_atpg_module_resolved():
    """The value the module would publish in its report is the SAME value the
    registered module resolved — that indirection is what makes the exemption
    cost no live coverage."""
    assert fsci._fatpg is far
    assert fsci._fatpg.DOCKER_IMAGE == far.DOCKER_IMAGE
