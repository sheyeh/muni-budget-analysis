# Handshake: level 3 output -> Postgres

Full schema for the persistent data model (`docs/adr/0004-postgres-supabase-data-model.md`
has the rationale; this doc has the concrete contract) plus the
`line_items.json` artifact level 3 must produce for the not-yet-built
Postgres loader (tracked in issue #13) to consume.

**Status: design, not implemented.** No level-3 code writes this shape
yet — `pipeline/analysis/` (the existing level-3 spike) predates this
contract and does not consume `normalized.json`/`scoped.json` yet either
(see `docs/handshake-level2-level3.md`'s "Gap" section). This doc exists
so level 3's eventual real implementation and the Postgres loader have
the same target to build against.

## Schema

### `muni` (dimension, ~200-250 rows, static)
| field | notes |
|---|---|
| `muni_id` | PK — semel yishuv, reused as-is (see `CONTEXT.md`'s "Muni ID"). **Caveat**: today's examples (901-910) are synthetic placeholders, not real semel-yishuv codes — no level-1 scraper exists yet (`docs/handshake-level2-level3.md`'s "muni_id caveat") |
| `name_he`, `name_en` | |
| `authority_type` | city / local council / regional council |
| `district`, `socioeconomic_cluster` (אשכול), `population` | CBS reference snapshot, not historized |

Populated from whatever level-1 (scraping) enumerates as the muni list — not invented here.

### `classification_code` (dimension, shared taxonomy, self-referencing hierarchy)
| field | notes |
|---|---|
| `code` | PK, e.g. `"631"` |
| `parent_code` | FK -> `classification_code.code`, nullable at root |
| `level` | depth in hierarchy |
| `category` | `income` \| `expense` |
| `standard_label_he` | canonical label per the national standard (תקן תקציבי אחיד) |

Seed data: `pipeline/analysis/moi_budget_codes.json` (~672 codes, parsed
from the official codebook PDF by `scripts/parse_codebook.py`) — promote
that into this table rather than re-sourcing.

### `budget` (one row per muni x attempted fiscal year)
| field | notes |
|---|---|
| `id` | PK |
| `muni_id` | FK |
| `fiscal_year` | the year the document is nominally for (target year, per `scoped.json`'s `target_year`) |
| `status` | `pending \| processed_success \| processed_partial \| processed_failed \| not_found` |
| `unit` | currency/scale for every line item in this document, e.g. `thousands_nis` \| `nis` |
| `source_ref` | pointer to `processed/{muni_id}/{filename_stem}/manifest.json` |
| `processed_at` | |

Unique on `(muni_id, fiscal_year)`. **A row only exists once something
was actually attempted** — no pre-seeded rows for the full expected
muni x year matrix. `not_found` means level-1/level-2 actively looked and
confirmed no document exists; a missing row means "not yet attempted."
The full expected-vs-found matrix is a query (`muni` x year range,
left-joined against `budget`), not a stored field.

### `budget_line_item` (fact table)
| field | notes |
|---|---|
| `id` | PK (bigint) |
| `budget_id` | FK -> `budget` |
| `muni_id` | FK, denormalized from `budget` — avoids a join for the dominant query shape (compare category X across all munis for year Y); safe because line items are wholesale-replaced per `budget_id` on reprocess |
| `classification_code` | FK -> `classification_code.code`, **nullable** (subtotal/header rows, or documents with no explicit code) |
| `row_type` | `line_item \| subtotal \| grand_total \| divider` — **required to avoid double-counting**: a `subtotal` row shares its `classification_code` with its own `line_item` children (it IS their sum). `grand_total` rows have `classification_code = null`. `divider` rows (bare structural headers, no values) should not reach this table at all. |
| `raw_label_he` | label text as it appeared in the source row, kept even when `classification_code` resolves, for audit/debugging |
| `category` | `income` \| `expense`, standalone (must still be known when code is null) |
| `fiscal_year_value` | the year *this amount* pertains to — decoupled from `budget.fiscal_year`. In practice, after level 2.5's scope-filtering, this equals `budget.fiscal_year` in the overwhelming common case (other years are dropped upstream as noise) — kept as a separate field defensively, not collapsed, per `docs/handshake-level2-level3.md`'s own warning not to assume `keep: true` means target-year data |
| `amount_type` | closed enum: `budgeted \| actual_current_prices \| actual_adjusted_prices \| execution_pct \| change`. `execution_pct`/`change` count as "structural, keep regardless of year" per ADR-0004's resolution of ADR-0003's open question |
| `amount` | numeric |

Reprocessing: `budget_line_item` rows are replaced wholesale per
`budget_id` on each run (`DELETE ... WHERE budget_id = X`, re-insert) —
idempotent, no versioning/history.

## `line_items.json` — level 3's output contract

One file per processed budget, parallel to level 2's `normalized.json`
and level 2.5's `scoped.json`, e.g.
`processed/{muni_id}/{filename_stem}/line_items.json`. Level 3 reads
`normalized.json` + `scoped.json` (when present, per
`docs/handshake-level2-level3.md`'s join logic) and resolves every kept
slice into this shape:

```jsonc
{
  "muni_id": 901,
  "fiscal_year": 2025,          // budget.fiscal_year / scoped.json's target_year
  "unit": "thousands_nis",      // budget.unit
  "line_items": [
    {
      "classification_code": "631",        // nullable
      "row_type": "line_item",             // line_item | subtotal | grand_total | divider
      "raw_label_he": "ארנונה כללית (מיסים)",
      "category": "income",                // income | expense
      "fiscal_year_value": 2025,
      "amount_type": "budgeted",
      "amount": 63403
    }
    // ... hundreds to 10K+ entries
  ],
  "warnings": [
    // any source column/row level 3 could not map to a known amount_type
    // or classification_code -- same warnings-non-empty-means-partial
    // convention as level 2's manifest.json
  ]
}
```

Notes:
- `budget.status` / `source_ref` / `processed_at` are **not** derived
  from `line_items.json` — they come from level 2's `manifest.json`,
  which always exists for an attempted file regardless of whether level
  3 succeeded. `line_items.json` only exists when level 3 produced at
  least partial output; a `failed`/`not_found` budget has no
  `line_items.json` at all.
- `warnings` non-empty => eventual `budget.status = processed_partial`,
  empty => `processed_success` — same rule level 2 already uses for its
  own manifest.
- `divider` rows (per `pipeline/analysis/`'s finding) should be dropped
  before they reach `line_items.json` — they carry no values.

## Loader (not built — issue #13)

Reads both `manifest.json` and `line_items.json` per processed budget,
upserts `budget` (from `manifest.json`, plus `unit` from
`line_items.json` when present) and wholesale-replaces that budget's
`budget_line_item` rows (from `line_items.json`'s `line_items`, when
present).
