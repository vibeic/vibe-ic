# Contributing to Vibe-IC

Thanks for your interest. This document explains the workflow, the
non-negotiable rules, and where to plug in if you want to add a skill,
wrap a new EDA tool, or report a regression.

## Code of Conduct

This project adopts the [Contributor Covenant v2.1](CODE_OF_CONDUCT.md).
By participating you agree to uphold it. Report violations to
**conduct@vibeic.ai** (private).

## Where things live

```
mcp-eda-server/           Node.js MCP server (24 tool wrappers + device fw)
vibe-ic-marketplace/
└── plugins/vibe-ic/      Claude Code plugin (skills, programs, agents)
    ├── skills/           One folder per skill — SKILL.md + assets
    ├── programs/         Deterministic checks / gates / generators
    ├── agents/           PM Agent, IC Expert Agent, lessons, defaults
    ├── flow/             Canonical Phase 1/2/3 flow YAML
    ├── tests/            Unit + integration tests
    └── ip_catalog/       Open-source IP catalogue
tools/                    CLI utilities (phase1 engine, regression)
docs/                     Architecture, design, tutorial notes
```

## How to contribute

### 1. File an issue first

For anything more than a typo fix, please open an issue describing
**what** is broken or missing and **why**. Use the issue templates
under `.github/ISSUE_TEMPLATE/`. Wait for a maintainer to triage before
sinking time into a PR — we'll save you rework.

### 2. Fork + branch

```bash
git clone https://github.com/<you>/vibe-ic.git
cd vibe-ic
git checkout -b fix/<issue-number>-<short-description>
```

### 3. Local development setup

```bash
# MCP server
cd mcp-eda-server
npm install

# Plugin tests
cd ../vibe-ic-marketplace/plugins/vibe-ic
pip install pytest
pytest -q
```

You also need:

- Docker (for `hpretl/iic-osic-tools`)
- Python 3.11+
- Node.js 20+

### 4. Make the change

Follow the design principles in the [main README](README.md):

- **Determinism over heuristics.** A new check is a Python program with
  a fixed verdict tier (PASS / PASS_WITH_WAIVERS / FAIL), not an
  LLM-judged "looks fine".
- **No stub modules.** Submitted RTL must instantiate every submodule
  end-to-end.
- **L9 Integration Spec first.** If you touch port naming, update the
  spec before the RTL.
- **Real-benchmark fixtures.** New walkers / regexes / merge logic must
  ship with a real-world doc-shape fixture under
  `tests/fixtures/real_benchmark/`.

### 5. Run the guards

The two hard gates that **must** pass before any PR is mergeable:

```bash
# (a) chip-AGNOSTIC source guard — no private IC / vendor / protocol names
python3 vibe-ic-marketplace/plugins/vibe-ic/programs/source_chip_agnostic_check.py \
        vibe-ic-marketplace/plugins/vibe-ic

# (b) Full test suite — BOTH plugin test trees + the MCP server
#
#     HARD RULE: validate with bare `pytest` from the plugin root. The plugin has TWO
#     test trees and you MUST run both:
#       - programs/tests/ : unit tests for the deterministic programs
#       - tests/          : integration/regression GATES (INDEX.md freshness,
#                           every-skill-has-compliance.yaml + test_compliance.py,
#                           orchestrator input-branch regressions, end-to-end skill audit)
#     pytest.ini pins `testpaths = programs/tests tests`, so bare `pytest` runs both.
#     NEVER validate with only `pytest programs/tests/` (or only `tests/`) — that silently
#     skips the other tree. A real on-main regression once slipped through exactly this way
#     (an orchestrator fix verified only against programs/tests/).
( cd vibe-ic-marketplace/plugins/vibe-ic && pytest -q )   # collects programs/tests/ + tests/
pytest -q mcp-eda-server/test
```

> Adding a program or skill? The `tests/` gates enforce registration: every new program
> must be in `programs/INDEX.md` (`python3 tools/gen_programs_index.py`), and every new
> skill needs `compliance.yaml` + `tests/test_compliance.py`
> (`_shared/bootstrap_compliance.py` + `_shared/gen_compliance_tests.py`).

### 6. Commit + push

Conventional commit style preferred but not strictly required:

```
fix(skills): correct register-map parser for AsciiDoc rowspan

Closes #123. Walker now handles `[cols="1,2,1"]` with a rowspan in
column 2. Adds real-shape fixture under tests/fixtures/real_benchmark/.
```

### 7. Open the PR

Fill in the PR template. Wait for at least one maintainer review.
We will run CI on merge to a temp branch first.

## Hard rules (PRs that violate these are blocked, not negotiated)

1. **chip-AGNOSTIC source.** No tokens from
   `tests/chip_deny_list.txt` may appear in tracked source. To add a
   new private name to the deny-list, edit that file directly.
2. **No `git push --force` on `main`.** Force-push to feature branches
   is OK if it's your own.
3. **No skipping pre-commit hooks** (`--no-verify`). Fix the hook
   instead.
4. **No silent waivers.** If a check is intentionally bypassed, add
   the rationale to `waivers.json` with a `review_required: true`
   flag plus an issue link.
5. **No bundled secrets / API keys / proprietary PDK files** in
   commits. Use environment variables and `.gitignore` for paths to
   licensed PDK installs.

## Adding a new skill

1. Create `vibe-ic-marketplace/plugins/vibe-ic/skills/<skill-name>/SKILL.md`
   following the template in `skills/_template/`.
2. Register it in `vibe-ic-marketplace/plugins/vibe-ic/flow/phase{N}.yaml`.
3. Add a deterministic check under `programs/` if the skill produces
   verifiable artefacts.
4. Add tests under `tests/`.
5. Document the skill in `docs/skills/<skill-name>.md`.

## Adding a new EDA tool wrapper (MCP)

1. Implement under `mcp-eda-server/src/index.js` following the existing
   `server.tool("eda_<name>", …)` pattern.
2. Add a manifest entry to `mcp-eda-server/devices_registry.json` if
   it's a device wrapper rather than a software tool.
3. Add tests under `mcp-eda-server/test/`.
4. **Add the entry to the [awesome-open-ic](https://github.com/vibeic/awesome-open-ic)
   list** under the appropriate category, marked with the green
   "MCP wrapped" badge.

## Reporting bugs

Use the bug-report issue template. Please include:

- Vibe-IC version (`vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json`)
- mcp-eda-server version
- OS + Python + Node versions
- Minimal reproduction (a `tests/fixtures/real_benchmark/` shape if possible)
- Expected vs actual output
- Any `flow_compliance_check.py --strict` output

## Reporting security issues

**Do not open a public issue.** See [SECURITY.md](SECURITY.md).

## License, DCO, and patent pledge

By contributing you agree that your contributions are licensed under
the [Apache License 2.0](LICENSE) along with the rest of the project.
Apache-2.0 §5 makes this automatic (inbound = outbound), and §3 grants
every downstream user an explicit **patent license** covering your
contribution — with the built-in defensive termination clause.

**DCO (Developer Certificate of Origin).** Every commit must carry a
`Signed-off-by:` trailer certifying you have the right to submit the
work under Apache-2.0 (the [DCO 1.1](https://developercertificate.org/)
text):

```bash
git commit -s -m "your message"
```

**Patent non-assertion pledge.** In addition to the Apache-2.0 §3 grant,
by contributing you pledge that:

1. you retain the copyright in your contribution;
2. you grant the Vibe-IC project and its users a perpetual, worldwide,
   irrevocable, royalty-free patent license covering your contribution
   (this restates Apache-2.0 §3 — nothing extra to do);
3. you will not assert, against any user of Vibe-IC, any patent claim
   that reads on your contribution as integrated into the project.

This mirrors the practice of patent-sensitive open-hardware communities
(RISC-V International's non-assertion covenants; the Linux Foundation's
DCO).

### Employer patent reminder (advisory, in the DCO spirit)

If you are employed, please confirm BEFORE signing off:

1. your employer agrees to you contributing code on your own time;
2. your employer agrees not to assert, against the Vibe-IC community,
   patents that read on your contribution;
3. if your contribution used employer resources (equipment, work time,
   confidential information), you have obtained written authorization.

These are **advisory**, not enforced — the DCO stays lightweight.
Corporate contributors may optionally use the one-page employer
consent template at
[docs/employer_consent_template.md](docs/employer_consent_template.md).
