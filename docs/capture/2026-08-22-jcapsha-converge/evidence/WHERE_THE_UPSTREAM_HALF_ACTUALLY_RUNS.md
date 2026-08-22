# The open question, answered: nothing runs it automatically, because nothing
# runs ANY test automatically

I left this open in the previous section — do the pins' upstream halves ever
execute at the gate, or are they green-over-nothing where it counts? Answered
by reading the only gate this repo has.

## There is no CI

`gatekeeper-ci.yml` **does not exist in the tree** (searched; no match). The
pre-push hook says why, in its own header:

    `gatekeeper-ci.yml` exists to run the governance programs as REQUIRED
    status checks. It has never run once. Actions is disabled at the ACCOUNT
    level — `HTTP 422: Actions has been disabled for this user.` — the appeal
    to GitHub Support was rejected, and twelve pushes to `main` produced zero
    runs. A self-hosted runner does not help: SCHEDULING is the blocked layer.

    So the checks CI would enforce are enforced HERE or nowhere.

## And the hook deliberately runs no pytest

    Mirrors gatekeeper-ci.yml's cheap deterministic gates. The expensive
    suites (plugin_full_audit, repo_hygiene_gates ~11 min) stay OUT: a hook
    slow enough to be bypassed is a hook that gets bypassed.

Measured: every `run_gate` call in the hook is a deterministic program (NDA
token scan, collateral-revert, version monotonicity, check-in scope, version
sync). **No pytest invocation anywhere in it.**

## So the answer is not about my pins

**No test in this repository runs automatically at any gate.** The pins are not
worse off than anything else; they are exactly as enforced as every other test
here, which is "when someone runs them". Running tests is, in the hook's own
words, "discipline, not enforcement".

That reframes what I can usefully do about it. I cannot make a gate run them —
there is no gate to attach to. What I can do is make running them cheap enough
that discipline is likely to happen, and record that they HAVE been run, at
this sha, against a named image by content.

## The one command, and its measured result

    docker run --rm --entrypoint sh -v "$PWD":/w -w /w \
      -e PYTHONDONTWRITEBYTECODE=1 ghcr.io/vibeic/vibeic-eda:0.3.24 -c '
      P=vibe-ic-marketplace/plugins/vibe-ic/programs
      python3 $P/upstream_contract_parity_check.py \
        --distribution-root /usr/local/lib/python3.12/dist-packages
      python3 -m pytest $P/tests/test_upstream_pin_pad_cfg.py \
                       $P/tests/test_upstream_pin_magic_lef.py -q'

MEASURED on this branch:

    BASIS: upstream re-read under /usr/local/lib/python3.12/dist-packages
           for 3 of 3 entry/entries.
    PASS: 3 registered re-implementation(s); every upstream name and every
          registered computation is accounted for.

    10 passed

Image identified BY CONTENT, not by a floating tag:

    ghcr.io/vibeic/vibeic-eda:0.3.24
    sha256:8658d4698220a47c2d40c91898b251ce9673e4f70488341b8ff44968f0f244b9

`docker run`, never `docker exec`.

## What this does and does not establish

It establishes that **on this branch, at this moment, all three register
snapshots are byte-current with the shipped distribution and both pins pass
their upstream halves**. It does not establish that they will be run again. The
BASIS line is the guard against the failure that matters more: a later reader
seeing a PASS and taking it for a statement about upstream when upstream was
never opened. That verdict now says which it is, every time.
