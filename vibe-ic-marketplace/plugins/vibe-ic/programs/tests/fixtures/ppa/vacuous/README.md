# `vacuous/` — the two ways of having nothing, which are not the same way

Hard rule, and this repository has paid for it three times in one day:

> **"I could not read it" and "I read it and it was empty" must never produce
> the same verdict.**

Both of them produce zero. Only one of them is a fact about the artefact.

This directory is the canonical pair, so that every lane tests against the same
two things instead of each inventing a temp file.

| path | what it is | what a consumer must do |
|---|---|---|
| `empty_but_present.rpt` | a real file, 0 bytes, readable | The file was read. It contains no rows. That is a MEASURED fact about the file and a NOT_MEASURED fact about the design: report `INVALID` — the artefact exists but cannot support the metric (contract §2) — and exit 2 with `[CANNOT CHECK]`. |
| `absent_report.rpt` | **does not exist, and must never be created** | Nothing was read. Report `NOT_MEASURED` with the reason "input absent" and exit 2 with `[CANNOT CHECK]`. |

Both exit 2. They are still different verdicts, and the difference is the whole
point: one says the producing step ran and wrote nothing, the other says the
producing step left no trace at all. Those call for different repairs, and a
consumer that collapses them tells the next reader to fix the wrong thing.

`test_ppa_fixture_integrity.py::test_the_absent_fixture_is_still_absent` fails
if anybody ever creates `absent_report.rpt`. That is not paranoia — a fixture
that quietly acquires content turns every negative test built on it green
forever, and nothing else in the suite would notice.

**Neither of these is rc=1.** rc=1 is a claim about silicon (contract §1).
Nothing here looked at any silicon.
