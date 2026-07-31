# Level 3: file analysis -- spike output

`pipeline/analysis/` (see its own `README.md` for setup/usage) is a
**spike**, not the real level-3 stage: it maps docling table rows to
Ministry-of-Interior budget codes and normalizes amounts to whole NIS.

`out/` and `summarize_data.csv` here are that spike's real committed
output (moved from the repo root, where they previously sat ungrouped
alongside every other stage's files -- issue #12).

## Known gap this reorg does not fix

`pipeline/analysis/` currently reads **docling's native `native.json`
export directly** (`pipeline/analysis/docling_rows.py`), not level 2's
`normalized.json` -- because it was built before
`src/muni_budget_analysis/processing` existed. That's no longer true (see
`../level2-processing/`). `docs/handshake-level2-level3.md` specifies the
contract level 3 should move onto; `pipeline/analysis/` has not been
updated to consume it yet. Flagged as a real follow-up, not fixed here
(out of this task's surgical scope -- this reorg is about where files
live, not rewriting the analysis pipeline's input source).
