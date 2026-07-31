# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Agent skills

### Issue tracker

Issues live in GitHub (`sheyeh/muni-budget-analysis`), uses `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout: `CONTEXT.md` + `docs/adr/` at repo root. See `docs/agents/domain.md`.

### Large files: never commit, always do the link trick

Don't `git add` a large binary (source budget PDF/Excel, docling native
export, etc. — roughly anything over ~2MB). Instead:

1. Add its exact path to `.gitignore`.
2. Host it externally (Google Drive is the existing convention — see
   `docs/examples/docling/tel_aviv_2026/native.json.link.txt` for the
   precedent) and commit a `{filename}.link.txt` sidecar next to where the
   file would have lived, containing: what the file is, why it's not in
   git (size), the hosting link, and how to regenerate/re-fetch it locally
   if that's possible.
3. If no hosting link exists yet (e.g. a newly-added sample file with an
   unknown source), still gitignore the binary and commit a `.link.txt`
   placeholder that says so explicitly — don't leave it silently untracked
   and don't fabricate a link.
