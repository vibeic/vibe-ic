"""A3 must start the simulator through a LOGIN shell, or it blames the netlist.

`verify_with_ngspice` launched ngspice through a NON-login shell:

    ["docker", "exec", container, "sh", "-c", f"cd {stage} && {ng} -b ..."]

A PDK's ngspice init file — the one that issues the `osdi` directives which
register compiled Verilog-A model types — is located by ngspice only through
`SPICE_USERINIT_DIR`, and that variable is exported by the EDA image's LOGIN
profile. Under `sh -c` it is unset, so the init file is never read, no
Verilog-A model type is registered, and ngspice:

    Unknown model type <va-type> - ignored
    Unable to find definition of model <scope>:<device>
    Simulation interrupted due to error!
    no simulations run!

and exits 1. `verify_with_ngspice` maps any non-zero rc to
`DID_NOT_CONVERGE`, so A3 records `NETLIST_NOT_SIMULATABLE` — "the rendered
netlist ... did not converge in the simulator" — and refuses to emit a deck
that is in fact correct. Measured: the SAME deck, SAME container, SAME
ngspice binary converges under `bash -lc` and reports `no simulations run!`
under `sh -c`; the working directory makes no difference.

`bash -lc`, not `sh -lc`: the image profile is bash syntax and aborts under
dash. Dropping the login shell was the wrong half of that earlier fix.

WHY IT HID: a PDK whose models are plain built-in SPICE types needs no
registration, so the non-login shell simulates fine — only a PDK that ships
compiled Verilog-A models can reach the defect. `analog_real_corner_sweep`
and `analog_a6_native_pv` already invoke the container through `bash -lc`;
this producer was the outlier.

chip-AGNOSTIC: no PDK, no device and no design is named — the assertion is
purely about the shell A3 asks docker for.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analog_a3_netlist_emit as A3            # noqa: E402


class _Result:
    """Enough of CompletedProcess for verify_with_ngspice to read."""

    def __init__(self, stdout: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


def _run_verify(monkeypatch) -> list:
    """Collect every docker argv `verify_with_ngspice` issues."""
    calls: list = []

    def _fake_run(argv, *a, **k):
        calls.append(list(argv))
        joined = " ".join(argv)
        if "command -v" in joined:
            return _Result(stdout="yes\n")
        if " -b " in joined:
            return _Result(stdout='MEAS vout= 1.0\n')
        return _Result()

    monkeypatch.setattr(A3.subprocess, "run", _fake_run)
    monkeypatch.setattr(A3.shutil, "which", lambda _n: "/usr/bin/docker")
    monkeypatch.setattr(A3, "_docker_ok", lambda _c: True)
    A3.verify_with_ngspice("c", "blk", "* netlist\n", "* tb\n")
    return calls


def _simulator_argv(calls: list) -> list:
    """The one call that actually runs the batch simulation."""
    sim = [c for c in calls if any(" -b " in part for part in c)]
    assert len(sim) == 1, f"expected exactly one simulator call, got {sim}"
    return sim[0]


def test_the_simulator_is_launched_through_a_login_shell(monkeypatch):
    """Not `sh -c`: that shell never exports the PDK init-file variable."""
    argv = _simulator_argv(_run_verify(monkeypatch))
    assert argv[:3] == ["docker", "exec", "c"]
    shell, flag = argv[3], argv[4]
    assert "l" in flag.lstrip("-"), (
        f"simulator started through a NON-login shell ({shell} {flag}); the "
        "PDK's ngspice init file is found only via a variable the login "
        "profile exports, so Verilog-A model types never register and every "
        "renderable netlist is recorded as DID_NOT_CONVERGE")


def test_the_login_shell_is_bash_because_the_profile_is_not_dash_safe(
        monkeypatch):
    """`sh -lc` was measured to abort on the image profile under dash."""
    argv = _simulator_argv(_run_verify(monkeypatch))
    assert argv[3] == "bash", (
        f"login shell is {argv[3]!r}; the EDA image profile is bash syntax "
        "and aborts under dash, which is what made an earlier fix drop the "
        "login shell entirely")
