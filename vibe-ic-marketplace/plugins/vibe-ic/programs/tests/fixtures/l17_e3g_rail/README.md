# `l17_e3g_rail` — the E3g fusion rail's population, owned by the test

One L17 channel catalog exercising every branch of
`l17_channel_catalog_consumer_contract_check`'s **E3g
CHANNEL_NAME_FUSES_DECLARED_SIGNALS** rail, plus the L9 the consumer reads.

E3g fires on a catalog entry whose `name` string enumerates two or more
terminals, because `phase2_scaffold_gen._sanitize_id` rewrites the delimiter to
an underscore and fuses the whole string into ONE port — so every member that
has no row of its own never reaches the top module.

| catalog entry | members | lost | fires | why |
|---|---|---|---|---|
| `sig_alpha / sig_beta` | 2 | 2 | ✅ | neither member has its own row |
| `sig_gamma, sig_delta, sig_epsilon` | 3 | 3 | ✅ | comma delimiter, three-way |
| `sig_zeta / sig_eta` (+ a `sig_zeta` row) | 2 | 1 | ✅ | PARTIAL — one member survives |
| `sig_theta / sig_iota` (+ both rows) | 2 | 0 | ❌ | redundant, not lossy |
| `sig_kappa / q` | — | — | ❌ | `q` is below `_FUSION_MIN_MEMBER_CHARS`, so the string is refused rather than split |

Totals: **3 entries reported, 6 declared signals lost.**

## Why these exist

`test_corpus_population_of_the_rail_is_pinned` asserted `len(rows) == 23`,
`sum(len(e)) == 62` and `sum(len(members_lost)) == 131`, counted over every
published cell under `benchmark-data/`; two neighbouring tests asserted `== 62`
and `== 131` again. Not one of those five integers is a property of the rail —
they are the size of the publication set, and they move whenever anyone
publishes or withdraws a cell. PR #1028 removes the corpus outright, at which
point all five go red for a reason that has nothing to do with correctness.

## The one number here that is load-bearing

`members_lost` vs the **N-1 arithmetic**. A fused port `AA_BB` is neither `AA`
nor `BB`, so no member is covered by it and there is no one to subtract; E3b
subtracts anyway. Over this fixture the honest total is **6** and N-1 would say
**4**, so the equality the test asserts is discriminating rather than
coincidental. The `sig_zeta / sig_eta` row is the case where N-1 happens to
agree (1 either way) — kept deliberately, so the discrimination is measured
over a population that contains one.

Every name here is synthetic and chip-AGNOSTIC.
