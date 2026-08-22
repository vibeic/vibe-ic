# `issue1080_confirmed_pair.json` — provenance

**This is CAPTURED data, not authored data, and not live data.** It is the
positive control for `competing_pr_claim_report.py` (vibe-ic#1411): the one
duplicate pair on this repo that was confirmed by hand.

Captured 2026-08-14 from the GitHub REST API of `vibeic/vibe-ic`:

```
gh api repos/vibeic/vibe-ic/pulls/1150 --jq '{number,title,body}'
gh api --paginate repos/vibeic/vibe-ic/pulls/1150/files --jq '[.[] | {path: .filename}]'
gh api repos/vibeic/vibe-ic/pulls/1205 --jq '{number,title,body}'
gh api --paginate repos/vibeic/vibe-ic/pulls/1205/files --jq '[.[] | {path: .filename}]'
```

The shape is exactly what `gh pr list --json number,title,body,files` emits, so
the fixture feeds `--prs-json` unmodified — the adapter is exercised on real
`gh` output rather than on a shape somebody guessed.

**One field is altered and it is stated here rather than left to be discovered:
`body` is TRUNCATED to its first line.** Both bodies are multi-kilobyte review
write-ups; the first line is the claim sentence (`Closes #1080.`), which is the
only part this report reads. Nothing else is edited. The file lists are
complete as the API returned them.

## Why this pair

Both PRs implement #1080 ("one metric schema so runs are comparable"). #1150
lands `run_metrics.py` with verdicts `BETTER / SAME / WORSE`; #1205 lands
`step_metrics.py` with verdicts `improved / REGRESSED`. Neither branch contains
the other's program. Landing both closes #1080 in name and defeats it in
substance.

**The only file they share is `INDEX.md`**, which every new program touches
because it is generated from every program's docstring. That is what makes the
pair the right control: with `INDEX.md` discounted (#1363) the pair is
`NO_SHARED_FILE` — invisible to a conflict — and without the discount it reads
as `SHARED`, i.e. as a group somebody would already have adjudicated. Both PRs
were merge-clean against each other on everything that carries meaning.

The pair was found by accident, while verifying #1150 for unrelated reasons.
Detail: https://github.com/vibeic/vibe-ic/pull/1150#issuecomment-5280407990

Both PRs are CLOSED today, which is why this is a capture and not a live query:
a control has to stay the same to be a control.
