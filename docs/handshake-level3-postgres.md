# Handshake: level 3 output -> Postgres

Full schema for the persistent data model (`docs/adr/0004-postgres-supabase-data-model.md`
has the rationale; this doc has the concrete contract) plus the
`line_items.json` artifact level 3 must produce for the not-yet-built
Postgres loader (tracked in issue #13) to consume.

**Status: Fully implemented and verified (July 2026).** The Stage 3 pipeline 
natively consumes `normalized.json` + `scoped.json` inputs and generates the 
production contract `line_items.json` output file for each processed municipality 
directory. This has been validated end-to-end against all 10 sample files.

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
| `amount` | numeric, pre-normalized to whole NIS (full ILS) |

Reprocessing: `budget_line_item` rows are replaced wholesale per
`budget_id` on each run (`DELETE ... WHERE budget_id = X`, re-insert) —
idempotent, no versioning/history.

## `line_items.json` — level 3's output contract

One file per processed budget, stored in the designated Level 3 analysis output directory, parallel to the Level 2/2.5 layouts:
`data/analysis/{muni_id}/{filename_stem}/line_items.json` (or `docs/examples/level3-analysis/{muni_id}/line_items.json` for example fixtures). Level 3 reads
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
      "amount": 63403000.0
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

## Resolutions of Prior Open Questions

The design gaps and open questions identified in the early drafting of this contract have been fully resolved and implemented:

- **`category` (income/expense) derivation path**: Resolved and implemented. The pipeline determines the category primarily by querying the Ministry of Interior's chart of accounts lookup `"side"` field (`"receipts"` -> `"income"`, `"payments"` -> `"expense"`). For `null` codes (e.g. section dividers or unclassified rows), the pipeline falls back to sequentially tracking the last seen section header (`"הכנסות"` / `"הוצאות"`) in document row order. This has been proven end-to-end on all sample budgets.
- **Unit granularity mismatch & Pre-normalization**: Resolved and implemented. All `amount` fields inside `line_items.json` are pre-normalized to whole NIS (full ILS) by multiplying raw cell values by the table-specific unit scale multiplier (e.g., multiplying by `1000` for `thousands_nis`). This simplifies downstream Postgres loading and queries, while the document-level nominal `unit` is still retained in the JSON's top-level metadata for provenance.
- **Column Semantic Resolution (`amount_type`/`fiscal_year_value`)**: Resolved and implemented. We added heuristic regex parsers that map Hebrew column headers to standard `amount_type` values (like `budgeted`, `actual_current_prices`, `execution_pct`, `change`), and extract 4-digit fiscal years (falling back to nominal budget target year when unspecified). `execution_pct` columns have their `amount` set to `null` to avoid double-counting.

## Loader (not built — issue #13)

Reads both `manifest.json` and `line_items.json` per processed budget,
upserts `budget` (from `manifest.json`, plus `unit` from
`line_items.json` when present) and wholesale-replaces that budget's
`budget_line_item` rows (from `line_items.json`'s `line_items`, when
present).
