#!/usr/bin/env python3
"""One `gh` invoker, because two of them drift apart.

`open_organic_issue_count` and `org_open_work_poll` each carried a
byte-identical `_gh`, differing only in a default timeout. That is exactly the
shape of vibeic-eda#29, where `branch_is_ours` existed in `check_pins_current`
AND in `daily_release` and the two gave OPPOSITE answers about the same four
pins — a divergence nobody could see, because each file looked self-consistent.

The contract that matters is the ERROR ENCODING, and it is the part most likely
to drift if copied: a `gh` that is not installed and a `gh` that failed must
never be reported as an empty result. Both map to a non-zero rc with the reason
in stderr, so a caller can tell "I asked and got nothing" from "I could not ask".

    127  gh is not on PATH
    126  the invocation itself failed (OSError / SubprocessError, incl. timeout)
    else gh's own exit code, with its stdout and stderr passed through

Deliberately NOT a general subprocess wrapper: it exists so that the two
GitHub-polling programs share one answer to "what does a failed query look
like", and a third one added later inherits it instead of inventing a third.
"""
from __future__ import annotations

import subprocess
from typing import List, Tuple

#: Generous, because a cold `gh` on a slow network is not an error. Callers
#: that poll many repositories in a loop pass something shorter.
DEFAULT_TIMEOUT = 120


def gh(args: List[str], timeout: int = DEFAULT_TIMEOUT) -> Tuple[int, str, str]:
    """Run `gh <args>`; return (rc, stdout, stderr). Never raises."""
    try:
        r = subprocess.run(["gh", *args], capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return 127, "", "gh not found"
    except (OSError, subprocess.SubprocessError) as exc:
        return 126, "", f"{type(exc).__name__}: {exc}"
