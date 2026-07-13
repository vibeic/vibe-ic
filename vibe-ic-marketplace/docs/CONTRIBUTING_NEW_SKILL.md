# Contributing — NEW_SKILL

This is a focused per-topic guide. For the umbrella partner-plugin layout
+ submission workflow, see [`CONTRIBUTING_PARTNER_PLUGIN.md`](./CONTRIBUTING_PARTNER_PLUGIN.md).

## What you ship

```
skills/<your-skill-name>/SKILL.md
```

## SKILL.md frontmatter (Claude Code spec)

```markdown
---
name: <your-skill-name>
description: One-paragraph description with NL trigger keywords. Claude auto-loads when user intent matches.
---

# <Your Skill Name>

(Body — methodology, mandatory rules, examples, references.)
```

## chip-AGNOSTIC + open-platform rule

Skills should NOT hardcode chip / vendor names in mandatory logic. Cite specific projects only as case studies (the reference plugin uses IC-A / USB-HID tester as case-study notation).

## Skill vs deterministic program — when to ship a skill

Ship a skill when:
- The work needs NL judgment / domain knowledge that can't be encoded in deterministic rules
- The user request is open-ended and benefits from AI dialogue
- Existing deterministic runners cover most cases but yours is a niche fallback

Ship a deterministic program (`programs/<func>.py`) when:
- The work is mechanical / verifiable / chip-AGNOSTIC
- Output should be reproducible across runs
- A gate / runner / generator role

## Classification

Add an entry to your partner plugin's `skills/_classification.json` indicating tier: `essential` / `analog_essential` / `fallback_when_runner_waives` / `rtl_track` / `backend_track`.
