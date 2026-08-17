"""Repo-root `tools/` pytest configuration.

ONE JOB: register the `campaign_tier` marker for the sessions rooted here.

`vibe-ic-marketplace/plugins/vibe-ic/pytest.ini` registers it for the plugin's
suite, but `tools/gatekeeper-land.sh`'s repo-tools arm runs from the REPOSITORY
ROOT over `tools/**`, where that ini is not the configfile. Without this file
pytest emits

    PytestUnknownMarkWarning: Unknown pytest.mark.campaign_tier - is this a typo?

on every landing — and that warning is the whole hazard in one sentence: an
unregistered mark is a silent no-op, so a misspelt `campaign_teir` would
deselect NOTHING while looking exactly like a working exclusion, and the arm
would keep printing PASS.

A conftest rather than a `tools/pytest.ini`: an ini file here would become the
configfile and move pytest's rootdir for this arm, which changes more than the
one thing that needed changing.

THE MARKER IS NOT THE RECORD. Every node carrying it is declared, with its
reason, the published artefact it audits and what runs it now, in
`vibe-ic-marketplace/plugins/vibe-ic/programs/landing_excluded_corpus.py`. That
program's `--audit` is wired blocking in `tools/ci/repo_hygiene_gates.sh` and
fails in both directions — a declared node that lost the marker, and a marked
node nobody declared.
"""


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "campaign_tier: audits a PUBLISHED campaign artefact rather than this "
        "change; deselected by the landing gate, declared in "
        "vibe-ic-marketplace/plugins/vibe-ic/programs/landing_excluded_corpus.py",
    )
