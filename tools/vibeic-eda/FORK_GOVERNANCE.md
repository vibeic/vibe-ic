# vibeic-eda — Fork Governance & Upstream-Tracking

> **Policy owner directive (2026-07-18).** Our forks are the **main line**. We do
> **NOT** push PRs upstream. We are the place people file PRs **to us**; we review and
> land them **in our own fork**. We only **pull-review** upstream (their bug-fixes,
> commits, releases) and decide whether to bring anything in. Divergence from upstream
> will grow as we move fast — that is an accepted cost.

## 1. The model — FORK-FIRST, INBOUND-PR-ONLY, PULL-REVIEW-UPSTREAM

```
          (their project)                         (our fork = the main line)
  ┌────────────────────────────┐          ┌──────────────────────────────────────┐
  │  upstream  (read-only ref) │          │  origin = vibeic/<tool>                │
  │  The-OpenROAD-Project/…    │  ──▶     │  we review upstream commits/releases   │
  │  YosysHQ/yosys, …          │  PULL    │  and CHERRY-PICK what we want in       │
  └────────────────────────────┘  REVIEW  │                                        │
                                           │  ◀── inbound PRs from ANYONE           │
        ✗ we never push PR upstream        │      we review (gatekeeper) + land     │
                                           │      the fix INTO our fork branch      │
                                           └──────────────────────────────────────┘
                                                          │  pinned SHA
                                                          ▼
                                              vibeic-eda image (Dockerfile REFs)
```

Three rules, binding:

1. **Fork-first.** `vibeic/<tool>` is canonical. All fixes/enhancements land here
   (feature branches, tracked in `FIX_STATUS.md` with a FAIL→PASS proof), then get
   pinned into the `vibeic-eda` image via `Dockerfile` `*_REF`.
2. **Inbound-PR-only.** External contributors open PRs **against `vibeic/<tool>`**.
   We review them (same discipline as the vibe-ic repo-gatekeeper: machine gates +
   Step-2.7 adversarial + NDA source-comment scan) and land them **in our fork**.
   We do **NOT** open PRs to the original upstream projects.
3. **Pull-review-upstream.** Periodically `git fetch upstream`, review their new
   bug-fixes / commits / releases, and **cherry-pick or merge** only what we judge
   worth bringing in. Upstream is a *reference we pull from*, never a target we push to.

### Remote convention (unified 2026-07-18, all 7 forks)
`origin` → our vibeic fork (push target).  `upstream` → the original project (pull-review only).

| tool | origin (ours, push here) | upstream (pull-review only) |
|---|---|---|
| OpenROAD | vibeic/OpenROAD | The-OpenROAD-Project/OpenROAD |
| yosys | vibeic/yosys | YosysHQ/yosys |
| magic | vibeic/magic | RTimothyEdwards/magic |
| netgen | vibeic/netgen | RTimothyEdwards/netgen |
| klayout | vibeic/klayout | KLayout/klayout |
| ngspice | vibeic/ngspice | danchitnis/ngspice-sf-mirror |
| iverilog | vibeic/iverilog | steveicarus/iverilog |

## 2. Inbound-PR mechanism (how someone contributes a fix to a forked EDA tool)

The **same two-layer model** the vibe-ic plugin already uses, extended to the tool forks:

- **Where to file:** a PR (or issue) **against the specific `vibeic/<tool>` fork**, on a
  branch off our current fork feature branch — NOT against the vibe-ic plugin repo, and
  NOT against the original upstream. (Plugin/flow bugs still go to `vibeic/vibe-ic`.)
- **PR must carry:** a reproducible **FAIL→PASS** proof (stock/old behavior → patched
  behavior), a **synthetic / open-PDK regression fixture** (NDA-clean — no commercial-PDK
  SKU/foundry/rule-id in the diff, comments, or fixtures), and 0-regression on the tool's
  existing test suite.
- **We (maintainers) review + land:** run the machine gates + a Step-2.7 adversarial read
  + the NDA source-comment scan; on green, land the commit **on our fork branch** and add
  a `FIX_STATUS.md` row. Then bump the `Dockerfile` `*_REF` and rebuild `vibeic-eda`.
- **CONTRIBUTING.md** on each fork states this (present on vibeic/OpenROAD + vibeic/yosys;
  TODO: add to magic/netgen/klayout/ngspice/iverilog — template in §4).

## 2.5 Who reviews the PRs — ONE Gatekeeper ROLE, per-repo machine GATE (owner decision 2026-07-18)

Every fork (`vibeic/<tool>`) AND the plugin repo (`vibeic/vibe-ic`) accept inbound PRs.
They are all resolved by **ONE unified repo-gatekeeper ROLE** — a single review identity
and a single set of principles — NOT by N independent maintainers with drifting standards.

The unification is of the **REVIEW DISCIPLINE**, not of the machine gate:

- **UNIFIED across every repo (the gatekeeper role — same for vibe-ic + all 7 forks):**
  1. **NDA source-comment scan** — no commercial-PDK SKU / foundry / rule-id in the diff,
     comments, or fixtures (the public-source-comment leak vector).
  2. **FAIL→PASS proof required** — reproducible stock/old → patched behavior.
  3. **Step-2.7 adversarial review** — §4.05 no-leak (a relaxation must not wave through a
     real defect; the negative/proven-negative is the load-bearing half).
  4. **Land discipline** — never `--force`/`--admin`/`--no-verify`; squash; record a
     `FIX_STATUS.md` row; bump the `Dockerfile` `*_REF` and rebuild `vibeic-eda`.

- **PER-REPO (the machine gate — different because each tool builds/tests differently):**
  | repo | machine gate (build + test) |
  |---|---|
  | vibeic/vibe-ic (plugin) | pytest (existing `gatekeeper_review.py`) |
  | vibeic/OpenROAD | cmake build + ctest (C++) |
  | vibeic/yosys | make + test (C++) |
  | vibeic/magic | build + test (C) |
  | vibeic/netgen | build + test (C) |
  | vibeic/klayout | build + test (C++/Ruby) |
  | vibeic/ngspice | configure + make check (C) |
  | vibeic/iverilog | build + ivtest (C++) |

  The vibe-ic `gatekeeper_review.py` (pytest) does NOT apply to a fork — a fork's gate is
  its own CI (build+test), declared per-repo. The gatekeeper runs *that repo's* gate.

**Flow for an inbound PR to `vibeic/<tool>`:** poll → run *that repo's* CI gate (machine) +
the unified NDA scan + Step-2.7 (agent) → on green, land on the fork branch + FIX_STATUS row
+ Dockerfile ref bump + `vibeic-eda` rebuild. Same role, same 4 principles, per-repo CI.

**Implementation (follow-up, not yet built):** extend the existing repo-gatekeeper into a
`fork-gatekeeper` loop that is fork-aware — polls every `vibeic/<tool>` for inbound PRs,
reads each repo's declared CI gate, applies the 4 unified principles, lands. The vibe-ic
repo-gatekeeper keeps resolving the plugin repo (pytest gate) unchanged; the fork-gatekeeper
is the same review discipline extended over the 7 tool forks with per-repo machine gates.

## 3. Fork-fix classification table (this session, 2026-07)

Every fix is a **vibeic-original** fork commit on our fork branch. "Upstream PR" column is
**intentionally N/A** per the no-push-upstream policy — kept only to record whether the
same class of bug also exists upstream (a *pull-review* hint for us, never a push target).

| tool | our fork branch | fix (commit) | class | exists upstream? (pull-review note) |
|---|---|---|---|---|
| OpenROAD | vibeic/post-route-detailed-routing-repair(-int) | transient/dynamic IR-drop `17dd65bfaf`; PEX LEF+.tf→OpenRCX converter `fc488b3db5`; PSM vectored L·di/dt `8851db1b5a`; DRT-0302 flat-macro PG-merge + rule-file-degrade `1cd84e502a`; OpenRCX coupling resistance-table segfault guard *(psm-transient, landing)* | feature-add / algorithm-hard / crash-guard | segfault guards + DRT crash-guards are generic robustness (upstream also affected) — do NOT push; note as pull-review parity check |
| yosys | vibeic/synth-fixes | functional-liberty ICG sound-LEC `7c8d7a282`; tri-state/`$readmemh`/D-latch; `lift_adder`; stat-0cell row | feature-add / bug-fix | stat-0cell + $dumpvars-class also upstream-affected; ours-first |
| magic | vibeic/{lvs-fidelity,bridge-tech-multimetal} | zero-width DEF route guard `8d7b0669`; NDR-via + SPECIALNET; crash/hang/startup trio `443eb4b6`; multi-metal bridge-tech `5e805d5a` | bug-fix / crash-guard | crash-trio is generic robustness (upstream affected) |
| netgen | vibeic/{lvs-fidelity,connectivity-match} | verdict/property + portless guard; `-auto-global`/`-nopower`/black-box; connectivity-based global match `cc6051f` | bug-fix / feature-add | verdict-line + portless are generic correctness |
| klayout | vibeic/{streamout-fixes,svrf-native-drc,klayout-signoff-int} | foundry layer-map + MANUFACTURINGGRID + merge-abutting `b82b6e9`; native SVRF DRC engine; GDS antenna deck + metal-fill `ded7f03fe` | feature-add | SVRF engine + signoff tools are vibeic-original (not in upstream) |
| ngspice | vibeic/batch-honesty | batch-honesty rc + per-.measure; `$&`-scalar; `.param` expand; native `.mc` Monte-Carlo; DC gshunt-homotopy `c89de02` | feature-add / bug-fix | batch-honesty rc is generic; native-`.mc` is vibeic-original |
| iverilog | vibeic/sv-tb-coverage | `->>` nb-event vvp codegen `e1e12f6`; comp-unit pkg ordering; `$dumpvars` forward-ref `bedf375` | bug-fix | $dumpvars-fwd-ref + pkg-ordering are generic; upstream affected |

(Full per-fix FAIL→PASS proofs live in `FIX_STATUS.md`. This table is the fork/branch/
provenance index; FIX_STATUS is the proof ledger.)

## 4. TODO to complete the mechanism
- [ ] Push each fork's fix branch to its `origin` (vibeic/<tool>) so the vibeic-org fork
      carries our work (verify yosys/ngspice branches are on the org, not only local).
- [ ] Add `CONTRIBUTING.md` to the 5 forks missing it (magic/netgen/klayout/ngspice/iverilog),
      stating the inbound-PR rule (file against this fork; FAIL→PASS + NDA-clean fixture; we land).
- [ ] Add an `upstream-sync` note per fork: last `git fetch upstream` reviewed + what (if any)
      was cherry-picked — so pull-review is auditable.
- [ ] **fork-gatekeeper (architecture decision, §2.5 — build it):** extend the repo-gatekeeper
      into a fork-aware loop that polls every `vibeic/<tool>` inbound PR, runs *that repo's*
      declared CI gate (per-repo build+test) + the 4 unified principles (NDA scan / FAIL→PASS /
      Step-2.7 / land discipline), and lands. ONE role, per-repo machine gate.
- [ ] declare each fork's CI gate (a `.github/workflows/gate.yml` or a `gate.spec` the
      fork-gatekeeper reads) — cmake+ctest / make+test / configure+make-check / ivtest per §2.5.

### CONTRIBUTING.md template (for the 5 forks missing it)
```
# Contributing to vibeic/<tool>
This is the vibeic fork of <upstream/tool> and is our MAIN LINE — we do not push
changes upstream; contribute here. Open a PR against this fork's current feature branch.
Your PR MUST include: (1) a reproducible FAIL→PASS proof (stock → patched); (2) a
synthetic / open-PDK regression fixture — NDA-clean: NO commercial-PDK SKU/foundry/rule-id
in the diff, comments, or fixtures; (3) 0 regressions on the existing test suite. A
maintainer reviews (machine gates + adversarial read + NDA source-comment scan) and lands
it on the fork branch; it then ships in the vibeic-eda image via the Dockerfile ref.
```
