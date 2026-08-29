# The enforcement hole: the lane refused correctly 49 times and stopped nothing

Measured 2026-08-29 on a fresh `--no-hardlinks` clone of `vibeic/vibe-ic` at
`6ae22986d5` (v1.12.43), `git status --porcelain` empty before any measurement.

## 1. The classification: 49 version-stamped landings, zero through the lane

Population, derived structurally rather than from message shape: every commit in
`40d0e14c0..6ae22986d5` whose `vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json`
`version` differs from its parent's. **49** (v1.11.95 … v1.12.43). All 49 also
carry a `[vX.Y.Z]` subject tag, so the two derivations agree.

**Method 1 — the landings' own notes.** `refs/notes/landing` holds 23 notes;
23 of the 49 carry one. Read in full:

* **0 of 23** claim the lane ran and passed. No note contains `ALL GATES PASS`,
  a stamp, or a green from `gatekeeper-land.sh`.
* **12 of 23** state the opposite in as many words —
  `SKIPPED: landing gate + pre-push hook (--no-verify), owner waiver`
  (d0c73aa09, v1.12.0);
  `direct to main, landing gate not used` (628ca251f, v1.12.8);
  and c4fba40c4 (v1.12.20), which names the cause exactly:

  > `SKIPPED: tools/gatekeeper-land.sh — owner-authorised; it judges ABSOLUTELY`
  > `and refuses on main's pre-existing reds, so it refuses every candidate today.`

* The remaining 11 describe what was run *instead* (per-module pytest at the
  pushed tree) and never claim the lane.
* The notes **stop** at v1.12.20 (2026-08-28 08:06). The last **26** landings,
  v1.12.21 … v1.12.43, carry no note at all.

**Method 2 — wall clock, independent of any note.** The stamp certifies the
exact pushed sha, so the lane must run on the tip *after* the previous landing;
the inter-landing gap is the whole time available. `tools/git-hooks/pre-push`
states the cost of `repo_hygiene_gates` + `plugin_full_audit` alone as `~11 min`,
and the lane runs both plus three test tiers and the review.

    gaps < 660s between consecutive version bumps:  45 of 48

Seven gaps are under 240s — less than the hygiene tier's own measured 239-241s
(`gatekeeper_review.py`, 2026-08-20). v1.12.17 landed **115 seconds** after
v1.12.16.

**Method 3 — shape.** All 49 are single-parent commits; none is a merge.

Nine of the 49 (v1.12.35 … v1.12.43) are the ones already disclosed as
`git push --no-verify origin HEAD:refs/heads/main`. The other 40 differ from
them in disclosure, not in path.

## 2. Was the rc ignored, or never produced? Neither — the lane never ran

The rc is produced **and honoured**. Chain, in the current tree:

    tools/gatekeeper-land.sh:1583   run_capture "full:repo-hygiene" … repo_hygiene_gates.sh --summary-json
    tools/gatekeeper-land.sh:1739   run_emit "full:repo-hygiene" "repo hygiene gates" --last
    tools/gatekeeper-land.sh:431      FAILED=1                     <- inside run_emit's FAIL branch
    tools/gatekeeper-land.sh:2047     rm -f …/gatekeeper-stamp
    tools/gatekeeper-land.sh:2071     exit "$FAILED"

`gatekeeper_review.py:1801 _hygiene_verdict` likewise returns `GateResult(rc=1)`
for any `FAIL` in the record. Nothing in the lane reads a red as a pass.

**The line that *does* let a non-zero through is on a path that no longer runs.**

    landing_merge_verdict.py:1254
        notes.append(f"gate fails on the base too, so it is not this "
                     f"branch's — {now_red[key]}")

`notes` never refuse; only `reasons` do. That is the two-arm differential, and
its only caller `tools/gatekeeper-verify-merge.sh` left the landing path when
`gatekeeper-land-differential.sh` was deleted at **c4e59efa7 (v1.12.1,
2026-08-28)**. Since then the lane judges **absolutely** — and says so at
`gatekeeper-land.sh:2050-2064`, whose remediation text ends:

> `then LAND and record those reds BY NAME in the commit message and in`
> `'git notes --ref=landing'`

That is the sanctioned procedure for a pre-existing red, and it is
`--no-verify`. The notes above are it being followed.

### A second, still-live hole: the forcing function shipped dead

`gate_red_since_check.inherited_red_reasons` (added v1.11.64, 30fae2d12) refuses
an inherited blocking red that no ledger row owns — `AN INHERITED RED WITH NO
OWNER`. It is reached only from `landing_merge_verdict.py:1370`:

    if red_since_ledger is None or commit_age is None:
        disclosures.append("INHERITED_RED_DEADLINE_NOT_EVALUATED")

and `--red-since-ledger` (`:1625`) **has no caller anywhere in the repository**
— `gatekeeper-verify-merge.sh:1639-1658` does not pass it, and
`git log -S'--red-since-ledger'` returns exactly the one commit that added the
flag. Neither of the two named reds has a row in `tools/ci/gate_red_since.json`
(which holds 2 rows, for other gates), so even with the differential restored
they would come due never.

## 3. The fix: the lane is skippable by anyone with push rights

Stated plainly, because it is the answer. Measured the same day:

    GET /repos/vibeic/vibe-ic/branches/main/protection -> 404 Branch not protected
    GET /repos/vibeic/vibe-ic/rulesets                 -> []
    GET /repos/vibeic/vibe-ic/actions/permissions      -> {"enabled": false}

`.git/hooks/` is untracked; `--no-verify` skips every client hook;
`gatekeeper-ci.yml` has never run. Nothing on the server asks anything.

**What this repo can actually use.** The repo is **public**, org-owned, and the
maintainer holds `admin`. Rulesets and branch protection are therefore available
(the `rulesets` endpoint answers `[]`, not `403`). A `pre-receive` hook is not —
that is GitHub Enterprise Server only. A required status check does **not** need
Actions: the context is fed by the Commit Statuses API.

So: `tools/ci/main_landing_ruleset.json` — `required_status_checks` on
`vibe-ic/landing-lane`, `non_fast_forward`, `enforcement: active`,
`bypass_actors: []` — plus `tools/ci/landing_status_publish.py`, called from
`gatekeeper-land.sh` at the two places it writes and removes the stamp, and
`tools/ci/main_ref_protection_check.py` as the rule's reader.

**Honest limit, not buried:** `status:write` travels with push access, so the
lander can forge the status. This makes an accidental skip impossible and a
deliberate one a separate visible act. It is not a cryptographic guarantee.
Closing that needs a GitHub App credential the lander does not hold.

**Operational cost, measured:** a status cannot be posted for a sha the server
does not have (HTTP 422, `No commit found for SHA`). Landing gains one step:
push the sha to any non-main ref, let the lane post the status, then push to
`main`. The direct-push doctrine survives; only the certification becomes
compulsory.

## 4. Falsification

Probe ref `refs/heads/enforce-probe/**` on the real repository, one variable,
`main` untouched throughout, every artefact deleted afterwards:

| state | command | exit |
|---|---|---|
| rule active, sha has no status | `git push` | **1** — `GH013 … Required status check "vibe-ic/landing-lane" is expected.` |
| rule active, sha has no status | `git push --no-verify` | **1** — identical refusal |
| rule active, status posted | `git push` | **0** |
| **rule deleted**, same statusless commit | `git push` | **0** |

The publisher, in a synthetic repo, `--dry-run`:

| input | result | exit |
|---|---|---|
| `--failed 0`, stamp matches, tree clean | `state=success` | 0 |
| `--failed 1` (single variable) | `state=failure` | 0 |
| `--failed 0`, stamp removed | REFUSED, nothing published | **2** |
| stamp restored | `state=success` again | 0 |
| `--failed 0`, tree dirty | REFUSED, nothing published | **2** |

`tools/ci/test_landing_enforcement_hole.py` — 20 passed. Every refusal assertion
is paired with the same fixture passing before the offending variable is
introduced.

The reader, run live against the real repository as it stands today:

    $ python3 tools/ci/main_ref_protection_check.py --live
    [FAIL] main_ref_protection: 1 finding(s) — `main` is reachable without the landing lane
        - NO RULESET TARGETS `main` …
    EXIT CODE = 1

## What was NOT done

The two red gates are untouched (owned elsewhere). No assertion weakened, no
`skipif` added, no tolerance widened, no `--write-baseline`. Nothing pushed to
`main`. The ruleset is **proposed and proven**, not installed: applying it to
`main` is a one-command act (`gh api -X POST repos/vibeic/vibe-ic/rulesets
--input tools/ci/main_landing_ruleset.json`) that changes everyone's landing
procedure and is the owner's to take.
