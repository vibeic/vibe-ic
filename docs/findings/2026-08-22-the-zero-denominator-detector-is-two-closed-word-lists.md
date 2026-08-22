# The zero-denominator detector is two closed word lists, and the repo's own house style is in neither

_Measured 2026-08-22 on host `8hd-3` at `cfae243dc`, using
`gate_zero_denominator_refuses_check`'s OWN `states_zero_population()` rather
than a reimplementation of it. Repository tooling only: no design, PDK, vendor
or part identifier appears._

## What was already established

The companion finding showed a program reporting `benchmarks=0` → `ALL_PASS`
rc 0, outside that gate's filename-shaped population of 570. The natural
conclusion is "widen the population". This document is why that alone would not
have caught it.

## The detector

    _ZERO_POP_RE matches exactly two shapes:

    1.  <verb> 0        verb in {analysed, analyzed, scanned, examined,
                                 audited, probed, inspected, read, processed,
                                 visited, collected}                    -- 10

    2.  0 <noun> ... <verb>
                        noun in {file, design, interface, net, cell, instance,
                                 module, pin, gate, record, entry, report,
                                 artefact, document, step, block, port, line,
                                 test}                                  -- 20

Both are CLOSED HAND-WRITTEN LISTS. Driven through the gate's own function:

| output | `states_zero_population` |
|---|---|
| `analysed 0 files` | True |
| `scanned 0 file(s)` | True |
| `benchmarks=0`  ← the real program's actual output | **False** |
| `benchmarks: 0` | **False** |
| `0 benchmarks` | **False** |
| `found 0 violations` | False (correct — that is a finding, not a population) |

`0 benchmarks` fails for a different reason from `benchmarks=0`: the number is in
the right place, and the NOUN is simply not one of the twenty.

## Why this is worse than a population gap

**The `label: N` form is this repository's house style for disclosing a
denominator.** All twenty instruments the frozen batch ships print exactly that:

    modules parsed:                 1296
    dual-selector parsers:            10

The detector matches none of it. So even after the population is widened — the
remedy both companion findings propose — a program that discloses `benchmarks: 0`
and exits 0 still passes, because the gate would probe it and see nothing.

Widening the population and leaving the detector alone converts an invisible
program into a probed program that silently agrees.

## What is NOT claimed

Not that the gate is worthless: it works, and it caught 24 refusals out of 25
zero-population statements on this tree. Not that any specific number of
programs currently slip through — establishing that means driving all 570
against empty projects in every disclosure form, which is the gate's own job and
not something a document should assert without running.

What is measured is the predicate's shape: two closed lists, three real forms
outside them, one real program emitting one of those forms, and the repository's
dominant disclosure convention matching none of the entries.

## The remedy is the one this branch keeps arriving at

Derive, do not enumerate. A zero population is a NUMBER IN A DENOMINATOR
POSITION — `<label><sep>0` or `0 <label>` where `<label>` is any noun — not one
of thirty words somebody thought of. The current lists are what
`enumerations must be derived from the tree` describes: they cover the cases the
author had seen, and the case that escaped is the one nobody had seen yet.

That change is a landing owner's call. Nothing here modifies the gate.
