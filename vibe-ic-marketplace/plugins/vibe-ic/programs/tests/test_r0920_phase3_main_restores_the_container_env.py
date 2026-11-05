"""`phase3_one_shot_runner.main()` gives the environment back.

WHY. The runner publishes the operator's `--container` choice into
`EDA_CONTAINER`, because several PDK-resolution helpers read it from there
rather than from the argument threaded through the steps. Inside the run that
is correct, and it is correct for every subprocess the run spawns. But this
program is also IMPORTED and its `main()` called in-process -- by the MCP layer
and by tests -- and `--container` DEFAULTS to a name, so one in-process run used
to leave every later PDK read in the same interpreter pointed at a container.

MEASURED on a8c7a3e74: `_pdk_layer_authority._environment_query` routes a PDK
read into a container whenever `EDA_CONTAINER` is set, so
`test_the_technology_answers_the_precheck_not_the_declaration` -- whose fixture
builds its technology under a `$PDK_ROOT` that exists only on the HOST -- was
41 passed alone and 9 failed / 32 passed after `test_phase3_delivery_admission`
(which calls `R.main()` in-process) ran before it in the same session. The gate
said "the technology's own layer table could not be read", which was true of the
container and false of the tree under test.

Both directions are pinned here: the variable is restored whatever it was, AND
the leak's actual consequence is reproduced from the environment variable alone,
so a future reader can see what the restoration is buying rather than take it on
trust.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
import phase3_one_shot_runner as R  # noqa: E402
from _tool_probes import skip_not_verified  # noqa: E402

_ENV = "EDA_CONTAINER"


def _run_main_on(project: Path) -> int:
    argv = [sys.argv[0], str(project)]
    old = sys.argv
    sys.argv = argv
    try:
        return R.main()
    except SystemExit as exc:          # argparse refusals are still returns
        return int(exc.code or 0)
    finally:
        sys.argv = old


def test_main_removes_what_it_published(tmp_path, monkeypatch):
    """No value before -> no value after, on a run that refuses immediately."""
    monkeypatch.delenv(_ENV, raising=False)
    _run_main_on(tmp_path / "no_such_project")
    assert _ENV not in os.environ


def test_main_restores_the_operators_own_value(tmp_path, monkeypatch):
    """A value before -> the SAME value after, never the run's default."""
    monkeypatch.setenv(_ENV, "an-operators-own-container")
    _run_main_on(tmp_path / "no_such_project")
    assert os.environ[_ENV] == "an-operators-own-container"


def test_the_publication_still_happens_inside_the_run(tmp_path, monkeypatch):
    """THE HALF THAT MUST NOT BE LOST: scoped is not removed.

    The helpers that read `EDA_CONTAINER` run DURING `main()`, so the value has
    to be in place then. Observed through the same module-level `os.environ`
    the helpers read, at the first point inside the run that can be reached
    without a project on disk.
    """
    monkeypatch.delenv(_ENV, raising=False)
    seen = {}
    real = R._delivery_admission_refusal

    def _spy(project, *a, **kw):
        seen["value"] = os.environ.get(_ENV)
        return real(project, *a, **kw)

    monkeypatch.setattr(R, "_delivery_admission_refusal", _spy)
    project = tmp_path / "proj"
    project.mkdir()
    _run_main_on(project)
    assert seen.get("value"), (
        "EDA_CONTAINER was not published while the run was executing; the "
        "PDK-resolution helpers read it from there")


def test_the_leak_this_restoration_prevents(tmp_path, monkeypatch):
    """THE CONSEQUENCE, reproduced from the variable alone.

    A PDK volume that exists on the HOST is invisible to `_pdk_layer_authority`
    while `EDA_CONTAINER` names a container, because the query is answered
    inside that container. This is what a leaked value did to every later
    reader in the interpreter.
    """
    import _pdk_layer_authority as PLA
    root = tmp_path / "pdks"
    (root / "hosttech" / "libs.tech" / "klayout" / "tech").mkdir(parents=True)
    monkeypatch.setenv("PDK_ROOT", str(root))

    monkeypatch.delenv(_ENV, raising=False)
    vol, why, _tried = PLA.resolve_volume("hosttech")
    assert vol is not None, why

    monkeypatch.setenv(_ENV, "a-container-that-answers-for-its-own-filesystem")
    leaked, why2, _t2 = PLA.resolve_volume("hosttech")
    if leaked is not None:
        # DECLARED, not a bare `pytest.skip` (vibe-ic#1128). With no docker
        # client there is no container route at all, so the leak this case
        # demonstrates cannot be reached here — and a verification that did not
        # happen must say so rather than read as a pass. The restoration itself
        # is still pinned by the three cases above, which need no container.
        skip_not_verified(
            "no container route from this host, so a PDK read cannot be "
            "diverted into a container and the leak is unreachable",
            "install a docker client, or run this file inside the pinned "
            "vibeic-eda image")
    assert "hosttech" in why2
