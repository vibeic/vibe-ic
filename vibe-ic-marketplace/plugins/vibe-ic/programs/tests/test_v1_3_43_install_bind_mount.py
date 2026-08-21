"""v1.3.43 candidate #4 — a clean install must start the EDA container with an
IDENTITY project bind-mount, else Phase 3's in-container `cd {host_path}` fails
("No such file or directory").

`phase3_one_shot_runner._to_container_path` translates host->container paths from
`docker inspect .Mounts`; a bare `sleep infinity` container has NO mounts, so the
host path is left untranslated and the in-container `cd` aborts. The plugin's
clean-install doc (repo-root docs/INSTALL.md) must therefore run the container
with the identity mount (host path == container path) plus the /foss/designs
mount for MCP-tool parity. This guards that doc.

PORTABILITY (path-portability fix): the mount source is the user-chosen
`$VIBEIC_DESIGNS`, NOT a shipped default under `$HOME`. `docker run` creates a
missing bind-mount source as root, so a hardcoded default materialised a phantom
directory on every clean install. The doc must therefore (a) use the variable,
(b) tell the user to `mkdir` it deliberately first, and (c) never name a
personal/product-internal default workspace.
"""
from pathlib import Path

import pytest

def _find_install() -> Path | None:
    """Repo-root docs/INSTALL.md lives ABOVE the plugin bundle; walk up until we
    find it (robust to worktree vs marketplace-cache nesting depth)."""
    here = Path(__file__).resolve()
    for anc in here.parents:
        cand = anc / "docs" / "INSTALL.md"
        if cand.is_file():
            return cand
    return None


def _install_text():
    p = _find_install()
    if p is None:
        pytest.skip("repo-root docs/INSTALL.md not present (cache distribution "
                    "without hand-synced repo-root docs) — skip")
    return p.read_text()


def test_install_docker_run_has_identity_bind_mount():
    txt = _install_text()
    # identity mount: host path resolves at the SAME path inside the container
    assert '-v "$VIBEIC_DESIGNS:$VIBEIC_DESIGNS:rw"' in txt, \
        "docs/INSTALL.md docker run must include the identity project bind-mount"


def test_install_docker_run_has_designs_root_mount():
    txt = _install_text()
    assert '-v "$VIBEIC_DESIGNS:/foss/designs:rw"' in txt, \
        "docs/INSTALL.md must also mount the /foss/designs MCP-tool designs root"


def test_install_explains_why_mount_required():
    txt = _install_text()
    # the note must explain the cd {host_path} failure the mount prevents
    assert "cd {host_path}" in txt or "cd " in txt
    assert "No such file" in txt
    assert "REQUIRED" in txt


def test_both_recommended_and_stock_blocks_mounted():
    """BOTH docker-run recipes (fork image + stock IIC-OSIC-TOOLS) carry the
    mounts — a user picking either path must not hit the Phase-3 cd failure."""
    txt = _install_text()
    # version-agnostic: the fork image tag bumps over time (was 0.2.2, now
    # 0.2.16+) — assert the image NAME + the stock image, not a pinned tag.
    assert "vibeic-eda:" in txt and "hpretl/iic-osic-tools" in txt
    # two identity mounts (one per docker run block)
    assert txt.count('-v "$VIBEIC_DESIGNS:$VIBEIC_DESIGNS:rw"') >= 2


def test_install_refuses_to_mount_a_nonexistent_designs_dir():
    """The phantom-directory guard, doc side.

    `docker run -v <src>:<dst>` CREATES <src> (as root) when it is missing, so a
    doc that hands the user a docker-run line with a defaulted host path makes a
    clean install materialise a directory the user never asked for. The recipe
    must therefore parameterise the location AND refuse to start when it does
    not already exist — letting docker create it is the bug.
    """
    txt = _install_text()
    assert "VIBEIC_DESIGNS" in txt, \
        "docs/INSTALL.md must parameterise the designs root as $VIBEIC_DESIGNS"
    assert '[ -d "$VIBEIC_DESIGNS" ]' in txt, \
        ("docs/INSTALL.md must guard docker run on the designs dir already "
         "existing, so docker never creates it as root")


def test_install_does_not_invent_a_home_workspace():
    """Renaming the phantom directory is not fixing it. The doc must not tell
    the user to create a plugin-specific workspace under $HOME as the default
    path — installing the plugin must add nothing to a user's home directory."""
    txt = _install_text()
    assert 'mkdir -p "$HOME/' not in txt and "mkdir -p $HOME/" not in txt, \
        "docs/INSTALL.md must not create a workspace under $HOME by default"
    assert 'export VIBEIC_DESIGNS="$HOME/' not in txt, \
        ("docs/INSTALL.md must not default the designs root to a $HOME "
         "subdirectory — point at a directory the user already has")


def test_install_names_no_internal_default_workspace():
    """`AI_IC_design` is this project's INTERNAL workspace name, not a sensible
    default for somebody else's machine. It must not appear as a shipped path."""
    txt = _install_text()
    assert "AI_IC_design" not in txt, \
        ("docs/INSTALL.md must not ship the internal `AI_IC_design` workspace "
         "name as a user-facing default")
