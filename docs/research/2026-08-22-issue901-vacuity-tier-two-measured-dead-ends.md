# The three `test_issue901_*` reds — the mechanism, and TWO fixes that are measured dead ends

agent `jred-ppa` · host 8HD-4 · 2026-08-22
subject **`a4caccefe`** (v1.11.69), clean worktree, nothing applied unless stated

This document exists so the next person does not spend these two attempts
again. **Nothing here was landed. No branch carries any of it.** Both fixes
below make the three reds green and both cause a worse regression than the one
they repair; the second does so *after* satisfying every test in the file it is
about, including the guard written to catch the first.

The three:

    test_issue901_structured_vacuity_reaches_the_step_verdict.py::
        test_GUARD_the_shipped_step_is_not_vacuous_when_its_sim_actually_ran
        test_the_shipped_step_names_the_one_clause_that_examined_nothing
        test_the_other_self_aware_shipped_gate_also_reaches_the_tier

They are red on `a4caccefe` in BOTH lanes (host and the pinned image), and they
are unrelated to the vacuous/waiver precedence change on
`next/ppa-layer-and-die-routing-reds` — measured byte-identical on that branch's
head and on pristine base.

---

## 1. The mechanism

`professional_tb_check`, over a tree with no producer report, discloses on BOTH
channels and exits 0:

```
$ python3 programs/professional_tb_check.py . --json .../professional_tb_check.json
{
  "gate": "professional_tb",
  "verdict": "NOT_APPLICABLE",
  "reason": "no professional_tb.json (step did not run)"
}
VACUOUS_PASS: professional_tb examined 0 testbench report(s) — no professional_tb.json (step did not run)
RC=0
```

`flow_compliance_check.check_step` resolves the LEGACY `VACUOUS_PASS:` bucket
BEFORE the structured one, and the legacy branch carries **no denominator**. So
one vacuous clause out of four that ran granted the WHOLE of step 4
`VACUOUS_PASS` — *"every executed sub-gate was vacuously satisfied"* — over a
tree whose sim ran, whose testbenches drive the unit, and whose coverage was
measured (`line=97.37% toggle=93.1% branch=95.0%`).

vibe-ic#901 added the count for exactly this case. It never gets to apply,
because the uncounted branch decides first.

---

## 2. Dead end 1 — give the legacy branch the same count

```python
elif (passed and vacuous_hints and not non_hint_reasons and not skip_hints
        and len(all_vacuous_cmds) >= len(ran_hints)):
```

Reddens `test_GUARD_the_legacy_channel_keeps_its_tier_when_siblings_ran`, which
exists to forbid precisely this and states the measurement in its own docstring:

> making the comparison govern `_VACUOUS_HINT_PREFIX` too turns six shipped
> expectations red, three of them steps leaving a disclosure tier and rejoining
> the executed-PASS numerator — among them
> `test_a9_simulation_only_is_disclosed::test_simulation_only_close_is_not_a_bare_pass`,
> i.e. an analog step that closed in simulation with no bench measurement
> anywhere becoming a bare PASS.

---

## 3. Dead end 2 — route a DUAL-CHANNEL discloser to the counted bucket

The subtler attempt, and the one worth writing down, because it looks correct
and passes the guard.

A clause that discloses on both channels is a structured discloser; only its
legacy echo reaches the uncounted branch. So exclude it there and leave
legacy-ONLY disclosers untouched:

```python
_json_vacuous_cmds = {r[len(_JSON_VACUOUS_HINT_PREFIX):] for r in json_vacuous_hints}
legacy_only_vacuous_hints = [r for r in vacuous_hints
                             if r[len(_VACUOUS_HINT_PREFIX):] not in _json_vacuous_cmds]
# ... and the legacy branch tests `legacy_only_vacuous_hints`
```

Result:

```
test_issue901_structured_vacuity_reaches_the_step_verdict.py    20 passed
```

**All twenty — the three reds AND the guard from §2.** The guard's fixture is a
legacy-ONLY discloser, so it is untouched by construction.

It still fails, for the reason the guard NAMED rather than the mechanism it
tested:

```
test_a9_simulation_only_is_disclosed::test_simulation_only_close_is_not_a_bare_pass
    pristine a4caccefe      12 passed
    with this change         1 failed
```

Verified against the pristine base, so it is caused by the change. **The analog
A9 gate also discloses on both channels**, so the same rule pulls A9 out of its
disclosure tier and hands it back to the executed-PASS numerator — a step that
closed in SIMULATION with no bench measurement reading as a bare PASS. Worse
than the under-disclosure being fixed.

---

## 4. Why both fail, and where the repair probably belongs

**Two different properties are riding one tier.**

* *"every clause that ran examined nothing"* — unanimity, which the count measures;
* *"this step closed without the measurement its verdict needs"* — A9's
  simulation-only close.

They are not the same fact. A9 is currently held out of the executed-PASS
numerator by the FIRST when what it is owed is the SECOND. Any rule sharp enough
to stop step 4 being falsely unanimous will pull A9 out too — unless A9 first
has a disclosure tier of its own to be held by.

So the repair most likely belongs in **how a simulation-only close is
disclosed**, not in the vacuity tier. That is a change to the analog disclosure
path with its own corpus, and it should be measured against that corpus rather
than improvised against these three tests.

A step held out of the executed-PASS numerator must not be handed back to it by
a fix for under-disclosure. That sentence is the whole constraint, and both
attempts above break it in the same place.
