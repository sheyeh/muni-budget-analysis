# `budget_filename` is synthesized to encode fiscal year, not the real source filename

The real scraped corpus (`data/`, see `docs/data-directory.md`) names each downloaded file after the source site's own timestamp (e.g. `1541058045.2762.pdf`) — no fiscal year appears in the filename anywhere. But level 2.5's `extract_year()` (`scripts/run_scope_classify.py`) determines the target fiscal year for scope classification by regex-matching `20\d{2}` against `source_filename`/`budget_filename`, and `scripts/build_level1_manifest.py` (issue #23, `prd-level1-corpus-ingestion.md` Task 1) is the first thing to feed real corpus records through that contract.

## Decision

`build_level1_manifest.py` synthesizes `budget_filename` as `{muni_dir_name}_{year}{ext}` (e.g. `32_מועצה_אזורית_גדרות_2018.pdf`) instead of reusing the real source-site filename. The real file is still read correctly — `source.value` is a genuine path to the real file on disk — only the *name* carried alongside it, and seen downstream in `normalized.json`'s `source_filename` field, is project-assigned rather than the literal name from the source site.

## Considered options

- **Add an explicit `fiscal_year` field** to the level-1 manifest record, and change `extract_year()`/`normalize.py` to read that instead of parsing a filename. Cleaner long-term — the year would be a first-class field instead of an encoding trick — but touches level 2.5 code and the `normalized.json` contract that level 3 also reads (`docs/handshake-level2-level3.md`), which this task's PRD explicitly keeps untouched ("this and its sibling issues stay within level 1->2->2.5 + Supabase dimensions... Level 3 ... [is] explicitly untouched here"). Rejected for *this* task, not necessarily forever — this ADR exists so a future implementer has the "why not now" on record.
- **Leave `budget_filename` as the real timestamp filename.** Rejected outright: `extract_year()` would find no year anywhere in the real corpus, so `scripts/run_scope_classify.py`'s `process_document()` would skip every real document at level 2.5 — the workaround exists specifically so the real corpus doesn't hit that dead end.

## Status

Implemented in `scripts/build_level1_manifest.py`. `extract_year()` and the `normalized.json` schema are unchanged. If a `fiscal_year` field is ever added to the level-1 manifest contract, `build_level1_manifest.py` can stop synthesizing filenames and `extract_year()` can read that field directly — not scheduled, just the natural undo path for this decision.
