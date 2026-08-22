## What this PR does

<!-- One-paragraph summary. Link the issue: "Closes #NNN" -->

## Type of change

- [ ] Bug fix
- [ ] New skill / new MCP tool wrapper / new device driver
- [ ] New deterministic check / gate
- [ ] New benchmark fixture
- [ ] Documentation / typo
- [ ] Refactor (no behaviour change)
- [ ] Test only

## How was this tested?

<!--
  Paste the commands you ran. At minimum:
    ( cd vibe-ic-marketplace/plugins/vibe-ic && ./run_tests.sh )
    python3 vibe-ic-marketplace/plugins/vibe-ic/programs/source_chip_agnostic_check.py \
            vibe-ic-marketplace/plugins/vibe-ic
-->

## PPA Appendix-C answers (optional today)

<!--
  `gatekeeper_review` runs `ppa_pr_scope_check`, which decides from your
  change-set WHICH of the twenty Appendix-C review questions apply, and reports
  how many did. Prose never satisfies a question; evidence a machine can
  re-verify does.

  Supplying answers is OPTIONAL right now, and the review says so rather than
  refusing. It becomes BLOCKING the moment you supply the file — every
  applicable question is then enforced, and marking an applicable question
  "N/A" is refused: the changed-surface detector decides applicability, not the
  author.

  Path: .github/ppa_pr_answers.json

    {
      "schema": "vibeic.ppa.pr_answers.v1",
      "answers": [
        {"question": 3,
         "evidence": [{"kind": "artefact", "ref": "reports/phase3/sta.rpt",
                       "sha256": "sha256:..."}]},
        {"question": 11,
         "evidence": [{"kind": "test",
                       "ref": "programs/tests/test_x.py::test_negative"}]}
      ]
    }

  See the module docstring of programs/ppa_pr_scope_check.py for the accepted
  evidence kinds and the exit-code contract.
-->

## Checklist

- [ ] I read [CONTRIBUTING.md](../CONTRIBUTING.md)
- [ ] `vibe-ic-marketplace/plugins/vibe-ic/run_tests.sh` passes (it is the full suite — bare `pytest` runs ONE tree by design)
- [ ] `source_chip_agnostic_check.py` PASSes (no private chip / vendor / protocol names)
- [ ] If I added a walker / regex / merge patch, I shipped a real-shape fixture under `tests/fixtures/real_benchmark/`
- [ ] If I changed behaviour, I updated the relevant `docs/` page
- [ ] If I bumped a version, I updated `plugin.json`, `marketplace.json`, and `package.json` together
- [ ] If I added a new MCP tool wrapper, I also opened a PR against [awesome-open-ic](https://github.com/vibeic/awesome-open-ic) to mark the upstream project as MCP-wrapped
- [ ] No `git push --force` on `main`, no `--no-verify`, no skipped pre-commit hooks
- [ ] No bundled secrets / API keys / proprietary PDK files
- [ ] (Optional) If I supplied `.github/ppa_pr_answers.json`, every applicable Appendix-C question carries machine-verifiable evidence — supplying the file makes the check BLOCKING
