# Level 2.5: row/column scope filtering -- example output

See `docs/adr/0003-llm-scope-classification-level-2-5.md` for the design
and `docs/handshake-level2-level3.md` for `scoped.json`'s full schema and
how level 3 should consume it.

## `poc/`

The original hand-transcribed proof-of-concept run (moved here from
`scripts/spike_output/scope_classify/`, which is now gitignored scratch --
this is the real sign-off deliverable, not throwaway). `FINDINGS.md` is
the level-3-team-facing writeup; the `*.request.json`/`*.response.json`
pairs are its 4 hand-picked table samples, predating `normalized.json`
existing at all.

## `{muni_id}/scoped.json`

Real output of `scripts/run_scope_classify.py` run against the real
`normalized.json` produced for every file in `budget_examples/` (see
`../level2-processing/`), closing the gap the POC's `FINDINGS.md` flagged
("this POC doesn't prove the classifier handles docling's raw
grouped-header output"). Capped at 3 tables classified per document (cost
guard -- see the script's docstring); `tables_classified` in each file
says how many of `tables_total` that covers. Same `muni_id` mapping as
`../level2-processing/README.md`.
