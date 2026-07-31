# PRD: Level 1 real corpus ingestion (bridge `data/` into level 2/2.5, plus Supabase dimensions)

## Context

`docs/data-directory.md` surveyed the real scraped corpus that now
exists on disk: 74 real municipalities, 525 scrape attempts
(`data/budget_files.csv`/`.json`), 512 downloaded files under
`data/{muni_id}_{name}/{year|general}/`. Every downstream design doc in
this repo (`docs/handshake-level2-level3.md`, ADR-0004, the level-2
tests) was written assuming level-1 scraping **did not exist yet** —
`muni_id` 901-910 are explicitly synthetic placeholders throughout. Issue
#8 already tracks this gap ("No Level-1 manifest yet mapping muni_id ->
real budget file URLs").

This PRD turns "we now have real scraped data" into an executable task
list: bridge `data/` into `run.py`'s (level 2) expected input shape, run
the real corpus through level 2 + level 2.5, and load the real dimension
tables (`muni`, `classification_code`) into Supabase.

**Scope boundary — read before touching anything downstream of level 2.5:**
level 3 (file analysis) and the level-3-to-Postgres handshake
(`budget`/`budget_line_item` tables, `line_items.json`, issue #13) belong
to a different team. Nothing here builds level 3, resolves its open
design questions, or edits `docs/handshake-level2-level3.md` /
`docs/handshake-level3-postgres.md`. Where our work would otherwise force
a change to either handshake, we work around it on our side and document
the patch instead (see Task 1's "Known workaround" below) — never edit
those docs to make our life easier.

Tasks 1, 2, 5 are ordered (5 gates 3; 1 gates 3). Task 4 is independent —
can run any time, in parallel with everything else.

## Task 1: Level-1 manifest adapter

**Goal:** produce the `[{muni_id, budget_filename, source: {kind, value}}]`
array `run.py`/`ingest.py` already expect (`resolve_source()` in
`src/muni_budget_analysis/processing/ingest.py`), sourced from the real
corpus instead of `budget_examples/`.

- New script: `scripts/build_level1_manifest.py`. Walks `data/` on disk
  directly — **do not trust `budget_files.csv`/`.json`'s `downloaded_path`
  column**, it's wrong (`data/budgets/{muni}/...` recorded vs. the real
  `data/{muni}/...`, confirmed against the actual tree in
  `docs/data-directory.md`). Skip `.DS_Store`.
- For every `data/{muni_id}_{muni_name}/{year}/{file}` (year folders
  only — `general/` is Task 2, not this task), emit one record:
  `{muni_id: int, budget_filename: "{muni_slug}_{year}{ext}", source: {kind: "local", value: "data/{muni_id}_{muni_name}/{year}/{file}"}}`.
- Cross-reference `budget_files.csv` by `(municipality_code, budget_year)`
  for `municipality_name`/`municipality_type`/`website_url` — useful
  provenance, carry it in the manifest as extra (non-contract) fields if
  convenient, but the four contract fields above are what `ingest.py`
  actually reads.
- **Known workaround (document, don't hide):** real filenames are
  source-site timestamps (`1541058045.2762.pdf`) with no year in them.
  Level 2.5's `extract_year()` (`scripts/run_scope_classify.py`) parses
  the target fiscal year from `source_filename` — unchanged by this task.
  Instead, this adapter **synthesizes** `budget_filename` to encode the
  year (`{muni_slug}_{year}{ext}`), so `source_filename` downstream still
  satisfies the existing contract. The filename level 3 eventually reads
  is therefore project-assigned, not the real source filename. Add a
  docstring at the synthesis site in `build_level1_manifest.py` stating
  exactly this, so a future cleaner fix (e.g. an explicit `fiscal_year`
  field instead of filename parsing) has a paper trail. Do not change
  `extract_year()` or either handshake doc as part of this task.
- Verify: no muni/year in the real corpus has more than one non-`.DS_Store`
  file (already confirmed true as of this PRD — re-check if `data/`
  changes), so no multi-file-per-slot handling is needed.
- **Excludes** `general/` files entirely (Task 2's problem, not this
  task's).
- Deliverable: `scripts/build_level1_manifest.py` + a way to invoke it
  (CLI, writes e.g. `data/level1_manifest.json` — gitignored, matches
  `docs/examples/level1-scraping/README.md`'s existing mention of that
  filename shape).

## Task 2: `general/`-file year triage

**Goal:** decide what to do with the 25 munis' `general/` files (9 of
which have *no* year folder at all — zero other data for those munis).

- These files carry no year signal anywhere — not in filename, not in
  directory structure (unlike the year-folder case Task 1 handles).
- Options to evaluate (not decided by this PRD — that's this task's
  point): open each file and read a title/header for the year (manual or
  LLM-assisted), or leave them out of the manifest entirely until a real
  year-detection approach exists.
- Independent of Task 1 — does not block or get blocked by it.
- Deliverable: a decision + (if not "defer") an extension to
  `build_level1_manifest.py` or a follow-up script.

## Task 3: Real-corpus level 2 + level 2.5 batch run

**Goal:** run the existing, unmodified pipeline against the real
manifest, producing real `normalized.json`/`scoped.json` per real
`muni_id` for handoff to the level-3 team.

- Inputs: Task 1's manifest. **Gated on Task 5's two bug fixes landing
  first** (both are pre-flight risks for a run this size).
- `run.py`'s `run_batch()` — unchanged, per `prd.md`'s Task 7 (already
  built, sequential/single-process, no worker pool).
- `scripts/run_scope_classify.py` — unchanged, still POC-shaped per
  ADR-0003, still capped at `--max-tables-per-doc` (default 3) as a
  cost/quota guard.
- Scale/cost planning needed before running: 992MB across the corpus,
  411 PDFs (some scanned, some 100+pp — per the GPU-tier precedent in
  `activity.md`'s Tier B/C runs against `budget_examples/`, this is not a
  laptop-scale run). Level 2.5 is one live LLM call per classified table;
  at ~65 munis (74 minus the 9 `general/`-only, before Task 2 lands) this
  is real spend, not a rerun of the existing 10-document POC.
- Output (`normalized.json`/`scoped.json` per real muni_id) is handed off
  as-is — this task does not consume it further; that's level 3's job.
- Deliverable: real `data/processed/{muni_id}/{filename_stem}/*` for as
  much of the corpus as succeeds, plus a batch summary (success/partial/
  failed counts) matching the style of `activity.md`'s prior runs.

## Task 4: Real dimension data load (independent — no dependency on Tasks 1/2/3/5)

**Goal:** replace the synthetic `muni`/`classification_code` seed data in
Supabase (`supabase/seed.sql`, currently `muni_id` 901-903 and a partial
code slice) with the real thing. Pure dimension tables — no
`budget`/`budget_line_item` involvement, so this doesn't touch the
level-3/DB handshake at all.

- `classification_code`: promote the full ~672-code taxonomy from
  `pipeline/analysis/moi_budget_codes.json` (already parsed by
  `scripts/parse_codebook.py`) into the `classification_code` table —
  per ADR-0004, "promote that into this table rather than re-sourcing."
- `muni`: real rows for the 74 munis found in `data/` (name/type from
  `budget_files.csv`), plus — for full coverage of the expected
  muni x year matrix per `CONTEXT.md`'s "Budget coverage" term — the
  complete ~200-250 municipality list from
  `src/muni_budget_analysis/scrapers/localities.py`'s output, not just
  the 74 with a found budget file.
- Deliverable: a migration/seed update (or a one-off load script) plus
  confirmation the existing schema
  (`supabase/migrations/20260730221726_init_schema.sql`) needs no
  changes — it already matches ADR-0004.

## Task 5: Two pipeline bug fixes (pre-flight for Task 3)

**Goal:** fix two real bugs surfaced by `activity.md`'s prior GPU runs,
before they hit a 400+ file real batch.

- **`TESSERACT_CMD` hardcoded Windows path**: `pdf_pipeline.py`'s
  `docling_pdf_ocr` path defaults to
  `C:\Program Files\Tesseract-OCR\tesseract.exe`, which crashes at
  model-init on any Linux/GCP host unless `TESSERACT_CMD` is set via env
  var. Fix: cross-platform default (e.g. resolve via `PATH`) or fail
  fast with a clear error instead of a hardcoded Windows default.
- **`run.py` output-dir collision**: output directory is
  `Path(budget_filename).stem`, so a muni-year with both a `.pdf` and an
  `.xlsx` would collide and overwrite. Not observed in the real corpus
  today, but Task 1's synthesized filenames make this a live risk to
  double-check. Fix: include the extension (or `pipeline_used`) in the
  output-dir key.
- Deliverable: both fixes landed in `src/muni_budget_analysis/processing/`,
  with regression coverage per whatever this repo's existing test
  conventions are (`tests/test_run_e2e.py` and neighbors).

## Verification

- Task 1: run `build_level1_manifest.py` against real `data/`, confirm
  every emitted record's `source.value` path actually exists on disk and
  every `budget_filename` parses back to the correct year via the same
  regex `extract_year()` uses.
- Task 3: after a real run, spot-check a handful of `manifest.json`
  `status` fields and confirm `normalized.json` exists for every
  `status != failed` record.
- Task 4: query `select count(*) from classification_code` (~672) and
  `select count(*) from muni` (~200-250) against the dev Supabase
  project.
- Task 5: add/extend unit tests exercising both bug scenarios (a
  Linux-style env without the Windows tesseract path; a synthetic
  manifest with both a `.pdf` and `.xlsx` for the same muni/year).
