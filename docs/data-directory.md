# `data/` directory

Local, gitignored (`data/` in `.gitignore` — nothing under it is tracked
in git; entirely reproduced by re-running the scraper). This doc records
what's actually on disk as of 2026-07-31 so agents don't have to re-derive
it. It's the level-1 (scraping) stage's output per `CONTEXT.md`'s pipeline
stages, and the input pool `src/muni_budget_analysis/processing/run.py`
(level 2) would consume — see `docs/examples/level1-scraping/README.md`.

## Layout

```
data/
├── budget_files.csv
├── budget_files.json
└── {muni_id}_{muni_name}/
    ├── general/
    │   └── {timestamp}.{ext}
    └── {year}/
        └── {timestamp}.{ext}
```

- **74 municipality directories**, named `{muni_id}_{muni_name}` (Hebrew
  name, e.g. `32_מועצה_אזורית_גדרות`). `{muni_id}` is the real muni ID
  (semel yishuv) per `CONTEXT.md`'s **Muni ID** term, not a synthetic
  placeholder.
- Under each muni dir, one subdirectory per **fiscal year** (`1993`–`2027`
  observed) holding that year's downloaded budget file(s), named after the
  source site's original filename/timestamp (e.g. `1541058045.2762.pdf`)
  — not renamed to anything meaningful.
- **`general/`** (25 of 74 munis) holds files the scraper couldn't
  attribute to a specific fiscal year — a muni's generic budget page had
  one link with no year in the text. 9 munis have `general/` only (no
  year dirs at all, e.g. `1034_קריית_מלאכי`, `1304_שוהם`); the rest mix
  `general/` alongside real year dirs.
- **File types**: 411 PDF, 61 `.xlsx`, 40 `.xls` (992MB total). A few
  munis (e.g. `1139_כרמיאל`) have native Excel budget files instead of
  PDF — relevant to `docs/adr/0002-excel-native-extraction-path.md`'s
  routing.
- **`.DS_Store`** (52 files) — macOS Finder noise, harmless, ignore.

## `budget_files.csv` / `budget_files.json`

Same 525 records in both formats (`json` has one extra `score` field per
row; csv has a BOM on the header). One row per scrape attempt, not per
downloaded file — 512 succeeded (`download_success=True`), 13 failed.

Columns: `municipality_code, municipality_name, municipality_type,
website_url, budget_year, file_type, download_success, downloaded_path,
file_size_bytes, source_url, link_text` (+ `score` in the json only).

- `municipality_type` is one of `עירייה` / `מועצה מקומית` / `מועצה
  אזורית`.
- `budget_year` includes a `0` sentinel for at least one row (uncategorized
  year — worth treating like `general/`, not a real fiscal year, when
  consuming this file downstream).
- **Known discrepancy**: `downloaded_path` is recorded as
  `data/budgets/{muni_id}_{muni_name}/{year}/{file}`, but files actually
  live at `data/{muni_id}_{muni_name}/{year}/{file}` (no `budgets/`
  segment) — confirmed against the real tree, e.g. muni `32`'s 2018 file
  is at `data/32_מועצה_אזורית_גדרות/2018/1541058045.2762.pdf`, not under
  `data/budgets/...`. Strip the `budgets/` segment when resolving these
  paths, or fix at the source if the generating script is ever found.
- The script that generated these two files isn't present anywhere in
  this repo (`git grep`/ripgrep for `downloaded_path` and `data/budgets`
  turns up nothing under version control) — it was run externally.
  `docs/examples/level1-scraping/README.md` still says the level-1
  scraper "not built yet," which this data contradicts; that doc hasn't
  been reconciled with this output yet.
