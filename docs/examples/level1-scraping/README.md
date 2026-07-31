# Level 1: scraping

The scraper has run externally (its own code isn't in this repo — see
`docs/data-directory.md`'s "known discrepancy" note) and produced the real
corpus at `data/`: 74 municipality directories, `budget_files.csv`/`.json`
(one row per scrape attempt), 512 downloaded budget files under
`data/{muni_id}_{muni_name}/{year|general}/`.

`scripts/build_level1_manifest.py` (issue #23,
`prd-level1-corpus-ingestion.md` Task 1) bridges that real corpus into the
**level-1 manifest** shape (`[{muni_id, budget_filename, source: {kind,
value}}]`) that `src/muni_budget_analysis/processing/run.py`'s
`load_level1_manifest()` / `ingest.py`'s `resolve_source()` consume as
input — see `CONTEXT.md`'s "Level-1 manifest" entry. It walks `data/`
directly rather than trusting `budget_files.csv`'s stale `downloaded_path`
column, and synthesizes `budget_filename` to encode the fiscal year since
the real filenames don't carry one (`docs/adr/0005-*`). `general/`-only
files (no year signal at all) are excluded — a separate task
(`prd-level1-corpus-ingestion.md` Task 2).

Run it with:

```
python scripts/build_level1_manifest.py
```

which writes `data/level1_manifest.json` (gitignored, local-only,
reproducible by rerunning the script against `data/`).

**Known gaps against the real corpus** (found while verifying against real
`data/`, out of scope for issue #23 to fix):
- Tel Aviv-Yafo (`muni_id=5000`) and Holon (`muni_id=6600`) have 2-6 files
  per year for most/all years (companion docs, or a multi-part PDF) —
  those specific muni-years are logged and excluded from the manifest,
  not guessed at. See issue #33.
- `extract_year()` (`scripts/run_scope_classify.py`)'s `20\d{2}` regex
  can't detect fiscal years before 2000; 6 real records (`muni_id=565`,
  1993-1999) are still included in the manifest (level 2 doesn't need the
  year) but will be silently skipped at level 2.5 until that regex is
  widened. See issue #34.

`src/muni_budget_analysis/scrapers/` (`localities.py`,
`municipality_websites.py`) is a separate concern — municipality list +
website resolution, not budget-file discovery/download. See
`docs/municipality_website_resolution.md`.
