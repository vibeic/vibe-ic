"""Keep an in-process A4 sweep away from the host's docker after #2238.

#2238 (0be153f26) runs every PVT corner in an INDEPENDENT container. Before
the launch the sweep needs a memory reservation -- an explicit
`VIBEIC_ANALOG_CORNER_MEMORY`, else the selected A4 container's own
`HostConfig.Memory` read through a real `docker inspect` -- then that
container's image (another real `docker inspect`), and then a real
`docker run` through `analog_corner_admission.launch`. All three are
host-side and fail CLOSED, which is right for a launch on a host.

The sweeps built by the suites below name their container "fake" and stub
`_docker`, the in-container command runner, so that the thing under test is
what the sweep DOES with a deck -- not where an admission read its numbers
from. Unstubbed, every one of them stopped at the first host-side read
(`cannot read selected A4 container memory declaration`, 23 reds across
four files on the first clean measurement after #2238 landed). This helper
declares the reservation the explicit way the sweep documents, keeps the
admission ledger out of the host's shared state directory, and routes the
image and the launch through the SAME fake the in-container commands already
go through: the launch's last simulation arg IS the ngspice command line, so
the fake answers it exactly as it answers `_docker`.

Nothing here reaches the admission's own suite
(`test_issue2236_aggregate_ram_admission.py`), which measures the real
reservation, ledger and argv against fakes of its own.
"""
from __future__ import annotations

import tempfile


def stub_independent_corner_launch(monkeypatch, sweep, fake_docker) -> None:
    """`sweep` is the imported `analog_real_corner_sweep`; `fake_docker` is the
    `(container, cmd, timeout=...) -> CompletedProcess` fake already installed
    as its `_docker`."""
    monkeypatch.setenv("VIBEIC_ANALOG_CORNER_MEMORY", "32g")
    monkeypatch.setenv("VIBEIC_ANALOG_CORNER_ADMISSION_STATE_DIR",
                       tempfile.mkdtemp(prefix="corner-admission-"))
    monkeypatch.setattr(sweep, "_corner_image", lambda container: "fake-image")
    monkeypatch.setattr(
        sweep._aca, "launch",
        lambda ledger, **kw: fake_docker("fake", str(kw["simulation_args"][-1])))
