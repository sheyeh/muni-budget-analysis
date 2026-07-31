# Muni Budget Analysis

Turning scraped Israeli municipal budget documents (PDFs, Excel files) into
a clean, structured, browsable dataset — so budgets that only exist as
scanned reports can be searched, compared, and mapped across municipalities.

The pipeline runs in stages: **scrape** budget files from municipality
websites → **extract** their raw structure (tables/sections, no
interpretation yet) → **scope** each table to the year we care about →
**classify** rows against Israel's standard chart-of-accounts → **load**
the result into Postgres → **browse** it on a small static web map.

## Quick start

Requires Python 3.9+.

```bash
git clone <this-repo>
cd muni-budget-analysis
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install                # needed for headless scraping
pytest                             # sanity check: should pass
```

Copy `.env.example` to `.env` and fill in what you need:

- `DATABASE_URL` — only if you're touching the Postgres loader (`scripts/load_*_to_supabase.py`).
- `SUPABASE_*` / `GEMINI_API_KEY` — only if you're running the Stage 3 LLM classification step.

Most day-to-day work (scraping, structural extraction, tests) needs none
of these.

To view the frontend locally:

```bash
cd web
python -m http.server 8000   # or any static file server
```

## Where things live

| You want to... | Look at |
|---|---|
| Understand the domain vocabulary (muni_id, normalized document, budget line item, etc.) | [`CONTEXT.md`](CONTEXT.md) — read this first, it's short and everything else assumes it |
| Understand *why* a design decision was made | [`docs/adr/`](docs/adr/) — one file per decision, numbered |
| See how scraping finds and downloads budget files | [`docs/budget_files_scraping.md`](docs/budget_files_scraping.md) |
| See how a municipality's website is resolved | [`docs/municipality_website_resolution.md`](docs/municipality_website_resolution.md) |
| Understand the handoff between pipeline stages | [`docs/handshake-level2-level3.md`](docs/handshake-level2-level3.md), [`docs/handshake-level3-postgres.md`](docs/handshake-level3-postgres.md) |
| Know what's in `data/` and how it's laid out | [`docs/data-directory.md`](docs/data-directory.md) |
| See what's been done recently, in plain language | [`activity.md`](activity.md) — running work log |
| File or find a bug/task | GitHub Issues on this repo — see [`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md) for label conventions |
| Find the actual pipeline code | `src/muni_budget_analysis/` — `scrapers/`, `processing/`, `analysis/`, `loader/` |
| Find the frontend | `web/` — plain HTML/CSS/JS, no build step |

If something in the code doesn't match what a doc says, trust the code and
please open an issue — docs drift, that's expected, flagging it helps.

## Project status

Actively evolving — schemas, stage boundaries, and even doc numbering are
still settling. Check open GitHub issues before starting significant work
to avoid duplicating something already in flight.

## License

MIT — see [`LICENSE`](LICENSE).
