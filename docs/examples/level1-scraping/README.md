# Level 1: scraping -- placeholder

Not built yet. Reserved location for level-1 example output once a
scraper exists: the level-1 manifest records (`{muni_id, budget_filename,
source}`) that `src/muni_budget_analysis/processing/run.py` consumes as
input, plus whatever raw provenance the scraper itself wants to keep.

`src/muni_budget_analysis/scrapers/` (`localities.py`,
`municipality_websites.py`) is the closest thing that exists today --
municipality list + website resolution, not budget-file discovery/download
itself. See `docs/municipality_website_resolution.md`.

In the meantime, `data/level1_manifest.json` and
`data/level1_manifest_gpu.json` (gitignored, local-only) show the shape
level-2's `run.py` actually expects, hand-written against
`budget_examples/` rather than scraped.
