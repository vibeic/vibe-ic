# Every landing is refused: `main`'s protected tuple matches neither authorised state

_Measured 2026-08-22 on host `8HD-6`, against `origin/main` at `81cd5321b`, with
the verifier's own code (`tools/ci/protected_landing_transition.py`) rather than
with a reimplementation of it. Pure repository landing machinery: no design, PDK,
vendor or part identifier appears._

## The headline, measured three ways

`build_receipt` refuses, identically, for **every** candidate — including a
candidate that changes nothing at all:

    main vs main (STEADY, no candidate change):  Refusal: protected tuple matches
                                                 neither authorised atomic state
    main vs its own parent:                      Refusal: (identical)
    an unrelated feature branch vs main:         Refusal: (identical)

The refusal does not depend on the candidate, because it is not about one.
`build_receipt` line 512 runs before any branch of its logic:

    base_files    = _observe_files(repo, base_commit, base_manifest["paths"], …)
    base_state_id = _match_state(base_files, base_manifest)   # <- unconditional

`base` is `origin/main`. `main`'s own protected tuple matches neither state its
own manifest authorises, so this raises before STEADY, ACTIVATE and PREPARE are
ever distinguished. **No landing of any kind can currently produce a receipt.**

The manifest itself is not malformed — `parse_manifest` accepts it. What is
wrong is the tree it describes.

## What is wrong with the tree

The manifest declares transition `landing-lane-parallel-window-v1`,
`current` = `eda-image-decouple-v1-next`, `next` = `activated-at-lane-parallel-window`,
over 47 protected paths, of which three are declared to move:

| declared to move | live bytes at `origin/main` |
|---|---|
| `tools/gatekeeper-land.sh` | `next` — activated |
| `programs/ci_harness_timeout_ceiling_check.py` | `next` — activated |
| `programs/landing_merge_verdict.py` | **a third state** |

and, outside the declared move entirely:

| not among the declared moves | live bytes at `origin/main` |
|---|---|
| `tools/ci/repo_hygiene_gates.sh` | **differs from `current`, and from `next`** |

Two distinct defects at once. The ACTIVATE for `landing-lane-parallel-window-v1`
is **incomplete and unfaithful**: two of its three paths landed, and the third was
edited *again* afterwards, so it is neither the state it left nor the state it was
authorised to reach. Separately, `repo_hygiene_gates.sh` **moved outside the transition the
manifest authorises**: `current` is the state `main` was in when that manifest was
authored, `repo_hygiene_gates.sh` differs from it, and it is not one of the three
paths the transition declares as moving. The manifest in the tree is the latest
one, so no later transition covers it either.

## Why a lane cannot fix this, even a well-behaved one

The obvious repair is a PREPARE: render a fresh manifest with
`tools/ci/protected_landing_manifest_author.py`, whose `current` is the live tuple
and whose `next` is what the following ACTIVATE installs. The lane authors its own
PREPARE — `gatekeeper_prepare_landing.py` handles the version, `programs/INDEX.md`
and the 63x8 census, and does not touch this manifest.

**That does not work here, and the reason is worth stating precisely.** The
PREPARE checks live at lines 527-540 and are only reached in the `else`
branch, *after* line 512 has already refused on the base. A candidate's new
manifest is never compared, because the base's own manifest and the base's own
tuple disagree first. A lane that renders a perfect PREPARE gets the same
Refusal, from the same line, as a lane that renders nothing.

So this was NOT repaired from the vibe-ic#1764 branch, and not only because it
would have been out of scope. Two reasons, and the first is sufficient:

1. **It would not have worked.** The refusal is on the base, before the candidate.
2. It would have been dishonest if it had. A `current` rendered against `main`
   today photographs — and thereby blesses — both an incomplete ACTIVATE and a
   protected path that moved with nothing authorising it, recording them as "the
   state we are leaving". That is re-baselining a red rather than fixing it,
   wearing a tool's clothes. An honest UNDETERMINED with the missing input named
   beats a manufactured PASS.

## Why the parity tests are not stale

`tools/ci/test_phase_b_activated_parity.py` has these red on a clean `origin/main`
with no changes in the tree:

    test_the_live_tree_is_exactly_one_recorded_state_and_never_a_mixture
    test_the_move_is_exactly_the_paths_the_two_states_disagree_on

That file's own header records it has had "the same disease twice" — twice pinned
to a spent transition, twice permanently red, which "trains the reader to ignore
the file" — and it was rewritten to assert PROPERTIES of whatever transition the
manifest describes, precisely so a later transition could not make it red.

It is red anyway, and that is the rewritten test working. The property it asserts
— the live tuple is exactly ONE recorded state, on every protected path — is false
on `main` today. Nothing about the test is out of date; a protected tuple is. It
was, in fact, the only thing pointing at a repository that cannot land.

## What has to happen, and who can decide it

Two questions a photograph cannot answer, so a landing owner has to:

1. **`programs/landing_merge_verdict.py`** — is its third state the intended
   content, so the transition should be re-rendered to reach it; or was it edited
   by mistake after ACTIVATE and should be restored to `next`?
2. **`tools/ci/repo_hygiene_gates.sh`** — which landing moved it after the
   manifest was authored, and was that move intended?

Once both are settled the live tuple can be made to equal one recorded state
again, at which point line 512 passes and ordinary PREPARE/ACTIVATE resumes.
`protected_landing_transition.py` ships a `bootstrap` subcommand
(`build_bootstrap_receipt`) that does not go through `build_receipt`; whether that
is the intended escape hatch for exactly this situation is the owner's call, not a
lane's.

## Reproducing it

    git worktree add --detach /tmp/wt origin/main && cd /tmp/wt
    python3 - <<'PY'
    import importlib.util, pathlib
    s = importlib.util.spec_from_file_location(
        "plt", "tools/ci/protected_landing_transition.py")
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
    repo = pathlib.Path("/path/to/the/repository")
    m.build_receipt(object_repo=repo, base="origin/main", candidate="origin/main",
                    candidate_gates=pathlib.Path("."),
                    candidate_tests=pathlib.Path("."))
    PY

To see the per-path breakdown instead, call `_observe_files(repo, "origin/main",
manifest["paths"], "sha1", 40)` and compare against `manifest["current"]["files"]`
and `manifest["next"]["files"]`. `sha1` is the repository's object algorithm;
passing `sha256` makes `_observe_file` refuse with "raw blob object disagrees with
its id", which is the probe being wrong rather than the tree.
