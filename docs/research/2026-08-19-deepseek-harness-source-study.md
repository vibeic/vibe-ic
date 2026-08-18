# deepseek-harness — source study against four measured vibe-ic defects

**Clone:** `99f6f02fecdb7dff40c3fbc9470f5907c29f74ca` — `99f6f02fe 2026-08-17
Merge pull request #2620 from deepseek-harness/release/dsh-0.1.0-rc.7`
(`git clone --depth 50 https://github.com/deepseek-ai/deepseek-harness`).
Every claim below cites a file:line in that clone.
vibe-ic side cited against worktree `2b93d8723` (v1.10.81).

Counted in the clone, not taken from any summary: `packages/` top-level = **54**;
leaf packages (`package.json`, excl. node_modules) = **226**; `invariant.ts`
files = **219**.

Supersedes `2026-08-19-deepseek-harness-mechanism-study.md`, which reported the
same four mechanisms from README/doc prose only. The verilog-eval material in
that file is filed as vibe-ic#1745 and is not repeated here.

---

## Verdict per mechanism

| # | Mechanism | Us vs them |
|---|---|---|
| 1 | Append-only SessionEvent log, replay/fork, interrupted-turn repair | **BEHIND on one property**, level elsewhere |
| 2 | Reversible effects on the Cordis Context | **LEVEL — and it does not solve our defect** |
| 3 | `packages/core/scope` registration primitives | **AHEAD** |
| 4 | Process-level sandbox vs our Docker | **AHEAD** |
| 5 | Per-package `invariant.ts` (the ledger's "completed port") | **AHEAD on enforcement, BEHIND on locality** |

---

## 1. SessionEvent log — BEHIND on one property

WHAT THEY CHECK. `packages/core/session/src/repair.ts:27` `interruptedTurnClosers`
is a pure function over the loaded log. It walks turn/step/call boundaries
(`:33-75`), and if a turn is still open (`:80`) it appends deterministic closers:

- `:92` `const started = callSeq !== undefined` — the discriminator. A `tool/call`
  event durably recorded means the call started; its absence means it did not.
- `:118-119` that discriminator becomes two distinct machine codes,
  `TOOL_OUTCOME_UNKNOWN` vs `TOOL_NOT_STARTED` (declared `:13,:16`).
- `:131` `turn/end` with `reason: { kind: 'interrupted' }`.
- `:85-86` seq continues from the last real event and the timestamp is **reused**,
  not invented — the comment says why: "never invents a 'future' time". That is
  what keeps repair deterministic and the log replayable.

Enforcement is separate and relational: `packages/core/session/src/invariant.ts:60`
`seq must strictly increase`; `:73` `turn/start while turn N is still open`;
`:87` `turn/end while step N is still open`. So an unbalanced log is a refusal,
not a silent read.

WHAT WE CHECK. `programs/_semantic_child_progress.py` — append-only FSM
`start -> checkpoint(unit) -> terminal` over an ordered manifest plus nonce, with
`NORECORD` explicitly "an operational recording lease, never a correctness
verdict" (docstring). `programs/_pytest_progress_plugin.py` — append-only
lifecycle events, one stream file per process. `programs/pytest_per_file_junit.py`
— owns the defect (#1654, measured 2026-08-15 at `1adbf3444`): a hang takes the
process down and a dead process writes no junit.

THE GAP. Ours is a **liveness** channel deliberately kept out of the verdict path.
`_pytest_progress_plugin.py` states it: *"This is a liveness channel, not verdict
evidence... JUnit plus the OS process return code remain the inputs to the landing
verdict."* Theirs puts the interruption **into the artifact the verdict reads**,
so a killed run cannot present as a clean one. Ours can: junit is absent, absent
yields an empty failing set on both arms, and empty minus empty is "no new
failures". That is the 94-file differential reporting 0/0.

We are AHEAD on the deadline itself — `pytest_per_file_junit.py` accepted the
deadline cannot be made to win and changed what survives the kill, whereas
`packages/guard/timeout-policy/README.md` documents that theirs is cooperative
and unenforced. We are BEHIND on exactly one property: **a run that died leaves a
typed record in the verdict channel**.

SMALLEST ADOPTION. Not event sourcing. Two things: (a) the arm driver writes an
INTERRUPTED sentinel into the verdict artifact set, so absence becomes a positive
record; (b) `landing_merge_verdict.decide` refuses on it rather than differencing
across it. `ABSENT` is already a first-class outcome there
(`landing_merge_verdict.py:255-262`) — the work is emitting it, not modelling it.

## 2. Reversible effects — LEVEL, and it does not solve our defect

WHAT THEY CHECK. `vendor/cordis/src/fiber.ts:83-93`: an `Effect` is a disposer, a
promise of one, or an iterable yielding several. `:95-101` `EffectMeta` carries a
label tree for diagnostics — "e.g. `ctx.on(\"event\")` or `ctx.provide(\"name\")`"
with nested `children`.

WHAT WE CHECK. `tools/ci/_gate_dispatch.sh:74-77` brackets every gate with
`git status --porcelain --ignored=traditional -- benchmark-data`; `--ignored` is
load-bearing because that class is invisible to plain `git status` while still
being read by the next gate. Measured damage recorded at `:69-71`: 1078 leftovers
in the main checkout, inflating the script's own declared-gate count from 68 to
169, and 13 phantom FAILs reproducing on two unrelated PRs.
`:567-575` pins `GATE_DISPATCH_JOBS=1` when the guard is active, with the reason
stated out loud: a shared-tree snapshot "can only be attributed to the gate that
ran alone inside it, and a run that names the wrong writer is worse than a slower
one."

THE GAP: **none — this mechanism is the wrong tool.** A Cordis effect is an
in-process registration with a disposer. It can only know resources acquired
*through the Context by cooperating code*. Our gates are subprocesses (`pytest`,
`git`, EDA binaries) that register nothing; a reversible effect would attribute
none of their writes. Adopting it would not let two gates run concurrently and
stay attributable.

The mechanism that WOULD is #4, not #2: a per-gate writable overlay makes
attribution a property of the mount. Their own `fiber.ts` also carries the hazard
we pinned against — the tutorial notes multiple async disposers run concurrently.

## 3. `packages/core/scope` — AHEAD

WHAT THEY CHECK. `packages/core/scope/src/index.ts:15` `ScopeKey = object` (opaque
identity); `:105` `Scope` (ctx + two teardown paths); `:137` `createScope`;
`:170` `scopeTarget`. `store.ts:159` `ScopedLayers` owns an eager global layer
plus lazily created exact-scope layers. This is **visibility and lifetime of
registrations** — who can see what a plugin registered, and when it is torn down.

WHAT WE CHECK. `programs/gate_discloses_denominator_check.py` (a PASS must say how
much it looked at) and `programs/gate_zero_denominator_refuses_check.py`, whose
docstring separates the two properties precisely: three gates returned a verdict
about a design they had not read, and "the P0 umbrella reads EXIT CODES, so a gate
that prints `0` in prose and returns `0` in rc contributes a silent pass". Plus
`_corpus_denominator.py`, `_gate_denominator.py`, `_corpus_location.py`,
`extraction_coverage_denominator_audit.py`, and `--corpus-may-be-absent` as a
declared flag across ~10 checkers.

THE GAP: none in this direction. Their scope does not answer "what was this check
allowed to see", and adopting it would not close our failure mode. The
transferable idea is next door in `packages/sandbox/sandbox-policy` — the mode
switch IS a log event and `effectiveSandboxMode(events)` folds it, making the
permission a value derived from the record. Our `gate_scope` is a runtime argument
that leaves no trace. Worth taking: have each gate emit its resolved scope (root,
glob, matched count) into its own record.

## 4. Sandbox — AHEAD

WHAT THEY CHECK. `packages/sandbox/sandbox-local/src/profiles.ts`:
- `:17` bwrap — `['--ro-bind','/','/','--dev','/dev','--proc','/proc','--die-with-parent']`,
  then `:19-20` a tmpfs `/tmp` and a writable bind of the workspace root.
- `:30-35` Landlock — `landlockGrantArgs({ readOnly: ['/'], readWrite })`.
- `:52` Seatbelt — `(version 1) (allow default) (deny file-write*)` plus writable
  subpaths.

All three are **filesystem-write fences and nothing else**. There is no
`--unshare-net`, no `--unshare-all`, no capability drop, no uid change anywhere in
this file; Seatbelt's `(allow default)` at `:52` explicitly permits everything
that is not a file write — network included.

WHAT WE CHECK. `tools/ci/protected_landing_transition.json`, profile
`vibeic-landing-hermetic-v1`: `cap_drop: ALL`, `network: none`, `read_only: true`,
`user: 65534:65534`, `no-new-privileges:true`, tmpfs mounts, and an image pinned
by digest `ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2…`.

THE GAP runs the other way. Ours guarantees strictly more on every confinement
axis, plus toolchain reproducibility (a pinned digest), which no process-level
sandbox provides. Theirs buys granularity (per-call, per-session, inside one
process tree), cost (a process jail is affordable per-gate; a container is not —
this is what makes the #2 overlay fix practical), and replayability.

## 5. The ledger item: per-package `invariant.ts`

### (a) What the pattern is

**One file per package**, next to the code it constrains, exporting a Cordis
companion plugin. `packages/core/session/src/invariant.ts:18-20`:

```ts
export const name = 'session-invariant'
export const inject = ['invariants']
```

It is loaded *beside* the package, never imported by it — `:1-3` "Load this
companion beside `@deepseek-ai/dsh-invariants` to enable the checks", and
`packages/runtime-diagnostics/invariants/src/index.ts:3-4` "ordinary package
entrypoints stay independent of diagnostics."

**Who runs it.** `InvariantRegistry` (`invariants/src/index.ts:94`), a Cordis
service. `register(packageName, installer)` at `:136`. `enabled` defaults to
**true** (`:96`). Selection is regex allowlist/blocklist over package names
(`:121-126`).

**What it refuses.** The installer receives a `fail` reporter bound to the owning
package (`:161-163`), which throws `InvariantError` (`:50`) carrying
`packageName` (`:54`) and the message `invariant violated by "<pkg>": <msg>`
(`:62`). For session, the refusals are relational log rules: `:60` seq must
strictly increase, `:73` no `turn/start` inside an open turn, `:87` no `turn/end`
with a step open.

**What makes it PER-PACKAGE and not global.** Three things, in the code:
1. Ownership is reserved by name and is exclusive — `:140-142` throws
   `package "<name>" is already registered`. Two packages cannot claim one rule.
2. Failures are **attributed** to the owning package, not to a central checker
   (`:62`).
3. A source-level meta-gate enforces that the companion exists and conforms:
   `scripts/verify-package-invariants.ts`, wired into `pnpm hygiene`
   (`package.json:129`).

### (b) Does `programs/` implement this shape under another name? YES

Searched `programs/` by name for `invariant`, `companion`, `owner`, `contract`,
`registry`, `register`; and by content for `invariant`. The shape exists, keyed on
**flow steps and L-layers instead of packages**:

- `programs/plugin_full_audit.py:11` — **D1, every program has a test**;
  `:17` — **D2, every step has a compliance checker**. That is the same meta-gate
  duty as `verify-package-invariants.ts`.
- The `*_contract_check.py` family — `l4_regmap_phase2_emitter_contract_check.py`,
  `l9_floorplan_contract_check.py`, `l11_otp_content_consumer_contract_check.py`,
  `l13_bringup_contract_check.py`, `l14_protocol_versioning_contract_check.py`,
  `l15_encoding_tables_contract_check.py`, `l17_channel_catalog_consumer_contract_check.py`,
  `l19_pdk_floorplan_contract_check.py`, `phase1_gate_contract_check.py` — each
  owns one subsystem's rules.
- `skills/layer-contract-doctrine/` — the doctrine, with its own `compliance.yaml`.

So the ledger item is **not** a task closed with no deliverable, and it is **not**
findable by searching for `dsh` or `invariant.ts` — the port landed under our own
vocabulary (contract / compliance / D1 / D2). What did NOT land is the *file
locality* (rules living in the subsystem's directory) and the *exclusive
ownership registry*.

### (c) Is the locality half worth having here? NO — and for a stated reason

It is a monorepo answer to a monorepo problem we do not have. Their locality is
load-bearing because a package is a **publishable unit with its own build,
manifest and dependency edges** — `verify-package-invariants.ts` checks manifest
and build wiring, which only exists because each package publishes separately. We
have one flat `programs/` in one plugin with no per-directory build, so moving
`l9_floorplan_contract_check.py` into an `l9/` directory would buy filesystem
adjacency and cost us the flat-namespace grep that every one of our audits
(D1/D2/D3, `gate_discloses_denominator_check`, the checker-execution wiring audit)
depends on.

The half worth taking is **exclusive ownership**: `invariants/src/index.ts:140-142`
refuses a duplicate registration. We have 1178 programs in one namespace and no
mechanism that says "this rule already has an owner" — which is precisely how a
duplicate checker gets written. That is a small, flat-tree-compatible ratchet.

---

## Checks of theirs that cannot fail

**1. `verify-package-invariants.ts` passes over an empty population.**
`scripts/package-invariants.ts:38` discovers owners with a hardcoded depth-2 glob
`globSync('packages/*/*/package.json')`. `:57-62` loops over that population;
`verify-package-invariants.ts:13` exits 1 **only** if `violations.length > 0`.
With zero owners the loop body never runs, `violations` is `[]`, and `:21` prints
`0 hand-owned package companion(s) conform.` and exits 0.

Measured in the clone:

```
real root  -> owners = 219   => loop runs, violations possible
empty root -> owners = 0     => loop body never runs, exit 0
```

This is the exact predicate `programs/gate_zero_denominator_refuses_check.py`
exists to find, and it is a **latent** defect, not a live one: I diffed the glob's
219 against the 226 leaf `package.json` files, and all 7 outside the glob are
`packages/typert/generator/tests/fixtures/**` — correctly excluded. The population
is honest today; the gate simply cannot tell a moved corpus from a clean one.

**We are AHEAD here, and it is checkable:** `programs/plugin_full_audit.py:29`
declares three exit states — `0 = D1+D2 clean / 1 = a real gap found /
2 = plugin_root not found` — and `:194` implements the `return 2`. "Could not
look" is a distinct outcome from "looked and found nothing". Theirs conflates
them.

**2. The invariant registry records reservation, not execution.**
`invariants/src/index.ts:129-131`: "The package name is reserved even when
filtering disables its checks", implemented at `:149` (`registrations.add`) before
the `selected()` test at `:154`. So `registrations` is true for a package whose
checks never ran. Nothing counts installers that actually executed. A
`package_blocklist` entry, or `enabled: false`, silences a package's rules while
leaving its registration indistinguishable from a live one.

**3. A zero-population early return in the preset warning.**
`packages/preset/agent-presets/src/index.ts:167`
`if (this.resolvedRoots.length === 0) return` — the "published without joining an
agent preset" warning is skipped entirely when no roots resolved. Advisory only
(a `logger.warn`, not a gate), so low consequence, but the same shape.
