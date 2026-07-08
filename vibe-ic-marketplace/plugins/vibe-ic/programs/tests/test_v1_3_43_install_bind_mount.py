"""v1.3.43 candidate #4 — a clean install must start the EDA container with an
IDENTITY project bind-mount, else Phase 3's in-container `cd {host_path}` fails
("No such file or directory").

`phase3_one_shot_runner._to_container_path` translates host->container paths from
`docker inspect .Mounts`; a bare `sleep infinity` container has NO mounts, so the
host path is left untranslated and the in-container `cd` aborts. The plugin's
clean-install doc (repo-root docs/INSTALL.md) must therefore run the container
with the identity mount (host path == container path) plus the /foss/designs
mount for MCP-tool parity. This guards that doc.
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
    assert '-v "$HOME/AI_IC_design:$HOME/AI_IC_design:rw"' in txt, \
        "docs/INSTALL.md docker run must include the identity project bind-mount"


def test_install_docker_run_has_designs_root_mount():
    txt = _install_text()
    assert '-v "$HOME/AI_IC_design:/foss/designs:rw"' in txt, \
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
    assert "vibeic-eda:0.2.2" in txt and "hpretl/iic-osic-tools" in txt
    # two identity mounts (one per docker run block)
    assert txt.count('-v "$HOME/AI_IC_design:$HOME/AI_IC_design:rw"') >= 2
