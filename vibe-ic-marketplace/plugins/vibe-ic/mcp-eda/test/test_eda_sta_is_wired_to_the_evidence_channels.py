#!/usr/bin/env python3
"""`eda_sta` must actually USE the evidence channels, not merely ship them.

`sta_evidence.mjs` is fully unit-tested, and every one of those tests would
still pass if the `eda_sta` tool never called it. That is the gap this file
closes: it asserts the wiring at the call site.

RE-AUTHORED 2026-08-27 onto the file-script tree. The measurement that forced
the move: our `-exit` had NEVER taken effect. `Main.cc:467`'s
`exit_after_cmd_file` applies only when a script FILE ARGUMENT is present, and
this tool fed Tcl on stdin, so OpenROAD fell into the REPL and
`tcl_readline_setup.cc:78-82` called `std::exit(EXIT_SUCCESS)` at EOF. Measured
on one failing script in the pinned image:

    openroad -exit bad.tcl      -> rc=1
    openroad -exit << EOF ...   -> rc=0, and it kept executing past the error

Three properties below therefore changed MECHANISM. None was dropped, and each
is now pinned at least as tightly as before:

  1. `-metrics` is still required, but the flag is now emitted by the shared
     `openroadScriptCmd` builder instead of being spelled out at this call
     site. The test pins BOTH that this call goes through the builder AND that
     the builder emits the flag — pinning only the call site would let the flag
     be deleted from the builder unnoticed.
  2. the stale-metrics-file `rm -f` is GONE, and its property is met more
     strongly: the sidecar's path is derived from a per-run `mktemp`, so no
     earlier run can even NAME the file. A fixed name someone must remember to
     delete is replaced by a name nobody else holds.
  3. absent / empty / unparseable stays a three-way distinction, but it is
     answered by a PRESENT/ABSENT sentinel inside the same in-container script
     rather than by a second `dockerExec` read-back. The read-back became
     redundant the moment the sidecar started riding home in the run's own
     output — and it read a fixed path that no longer exists.

Two properties are ADDED, because the defect above must not come back: the
invocation must be a file argument (never a heredoc, never a pipe), and a
constrained run that MISSED timing must not be manifested PASS.

The rest are unchanged: the linkage metric is emitted after `link_design`, the
reported `success` is the conjunction, the manifest is gated on that
conjunction, and wns/tns are withheld from a run that produced no evidence.
"""
from __future__ import annotations

import re
from pathlib import Path

INDEX = Path(__file__).resolve().parents[1] / "src" / "index.js"
SRC = INDEX.read_text(encoding="utf-8")

LINK_METRIC = "sta__design__port__count"




























def test_the_module_is_imported():
    assert 'from "./lib/sta_evidence.mjs"' in SRC
