# POC findings — level 2.5 row/column scope classification

Ran live against Vertex AI `gemini-2.5-flash` (project `qwiklabs-gcp-03-e1024cd263b6`, a temporary Qwiklabs training project — same one used for the earlier `gcp-gpu-spike` worktree; not persistent, get a real project for production use per ADR-0003/`docs/gcp-gpu-docling.md`'s existing note on this). `google-genai` not yet in `requirements.txt` — added only for this spike.

Note: `gemini-2.0-flash-001` (the model ADR-0003 originally named) no longer exists on this project's Vertex AI endpoint (404) — swapped to `gemini-2.5-flash`, the current stable flash tier. Update ADR-0003 to not pin a model version that will drift.

## Results — all 4 samples correct on first run

| Sample | Expected | Got | Verdict |
|---|---|---|---|
| `even_yehuda_2025_main_table` | column axis, only 2025 col + label kept | column axis, 2025 col + label + 3 non-year columns kept | ✅ |
| `jerusalem_2026_debt_forecast_row_axis` | row axis, only 2026 row kept | row axis, only 2026 of 15 rows kept | ✅ |
| `jerusalem_2026_debt_breakdown_no_target_year` | all data cols excluded (only 2024/2025 present, target=2026) | all data cols excluded, only label + 2 non-year ratio cols kept | ✅ |
| `jerusalem_2026_staffing_nested_headers` | 2026 sub-columns kept, 2025 sub-columns excluded | exactly that | ✅ |

## Judgment calls worth level-3-team sign-off

The model's `keep=true` calls for **non-year structural columns** (beyond the obvious row-label column) are defensible but not obviously "correct" — this is exactly the kind of contract detail the POC is meant to surface before it's built into the pipeline:

- `even_yehuda`: kept `מקדמים בשימוש הרשות` (a 2024 execution-rate %) and `שינויים כולל התייעלות` (a 2024→2025 delta column) as "structural." Both are arguably still 2024-derived, not 2025 data — model chose to keep them as context/explanatory columns rather than exclude as off-year. Reasonable, but a different design could exclude anything that isn't literally the target-year column.
- `jerusalem_debt_breakdown`: kept the two "% of total" distribution columns even though the table itself has no 2026 data at all — treated as always-relevant proportions rather than year-tied. Same category of call.

Recommend the level 3 team explicitly weigh in on: should "keep" mean *only* target-year values plus the bare minimum to identify the row (code/label), or is context like execution-rate/delta columns wanted alongside it? This changes what `keep=true` means in the contract.

## Schema deviation observed

Prompt said `"rows"` present only if `year_axis == "row"`, `"columns"` present only if `year_axis == "column"`. In practice, for the row-axis sample the model returned **both** `columns` (every header, all `keep: true`, `detected_year: null`) and `rows` — harmless (consumer just reads whichever key matches `year_axis`), but not strictly what was asked. Real implementation should either accept this (ignore the non-matching key) or use provider-enforced structured output (JSON schema / function-calling response schema) instead of a free-form-JSON system prompt to eliminate the ambiguity.

## Known gap not covered by this POC

`jerusalem_2026_staffing_nested_headers`'s input headers were hand-cleaned (each header string already has its year folded in, e.g. `"שיא כוח אדם בתקנים 2026"`). The real docling extraction of that table (`document.md` lines 351-375) has a genuinely messy multi-row/merged header (`תקציב 2026` spans 3 sub-columns, `תקציב 2025` spans 3 more, docling's markdown export doesn't cleanly associate them) — normalize.py's actual column-header strings for a table like this are unknown until level 2's Task 7 (batch `run.py`) lands and produces a real `normalized.json`. **This POC doesn't prove the classifier handles docling's raw grouped-header output — only that it handles the same information once flattened into per-column text.** Flag this as a real risk for the first full-corpus run, not just a hypothetical.

## Operational note

Hit a transient `429 RESOURCE_EXHAUSTED` on the first attempt (qwiklabs project quota), succeeded on retry ~15s later. Full implementation's batch runner should retry on 429 (not treat it as a hard per-file failure) given `run.py`'s existing "a failed/partial file must not crash the batch" requirement.
