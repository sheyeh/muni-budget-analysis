# Stage 3: category & unit normalization (spike)

Turns docling's raw table extraction for one municipal budget document into
a common format across municipalities: every row's label matched to a code
in the Ministry of Interior's official chart of accounts ("ספר קידודים"),
and every amount normalized to whole NIS regardless of whether the source
document reports in thousands or full shekels.

**Status: spike.** This proves the approach works before it's formalized as
a real stage 3 (see `CONTEXT.md`'s "budget line item" entry) sitting behind
stage 2's `normalized.json` contract, which doesn't exist yet
(`pipeline/processing` is unbuilt — see `prd.md`). For now this reads
docling's native export directly. It also doesn't yet resolve fiscal
year / amount type (budgeted vs. actual) per column — see Limitations.

## One-time setup

```
pip install -r requirements.txt
```

Parse the codebook PDF into `pipeline/analysis/data/moi_budget_codes.json`
(only needs re-running if `scripts/parse_codebook.py` changes, or the PDF
does):

```
python scripts/parse_codebook.py
```

Prints a summary (~672 codes) and any parsing warnings.

## Get a Gemini API key

Create one at https://aistudio.google.com/apikey. **Never commit it or
paste it into a chat/log** — every script here takes it as a `--api-key`
argument (or reads `GEMINI_API_KEY` from your own shell), and never reads
it from a file in the repo.

**Free-tier daily quota**: as of writing, the free tier caps `gemini-3.6-flash`
at **20 requests/day/model**, and each *table* (not each document) is one
request — a document with an income table and an expense table uses 2.
This is a hard per-day cap, not a per-minute throttle: `spike_category_mapping.py`
retries transient 429s/5xxs automatically, but a daily-quota 429 fails
immediately instead (retrying it wouldn't help — see the `QuotaExhaustedError`
message). Running the full ~200-file corpus later will need either a paid
tier/higher quota, or spreading runs across days/API keys.

## Get input: a docling native.json per document

This spike consumes docling's native export (`DoclingDocument.export_to_dict()`),
not a PDF directly. If you don't have one yet:

- Generate one with `scripts/spike_docling.py` (see its docstring), or
- Pull an existing example out of `origin/docling-example-outputs` (a
  branch of example outputs, not merged and not a dependency of this code
  — it may change independently):
  ```
  git show origin/docling-example-outputs:docs/examples/docling/<name>/native.json > path/to/local.json
  ```

Three examples are already checked into this branch under
`docs/examples/docling/<name>/native.json` (`elyakin_2026`,
`even_yehuda_2025`, `mate_yehuda_2024`).

## Run it: single document

```
python scripts/spike_category_mapping.py --api-key YOUR_KEY \
    --input docs/examples/docling/even_yehuda_2025/native.json \
    --source even_yehuda_2025 \
    --out out/even_yehuda_2025.json
```

`--input`/`--source` are repeatable (same order) to process several
documents in one process and combine them into one `--out` file; or use
`--out-dir` to write one `<source>.json` per document instead.

## Run it: a whole directory

Auto-discovers one document per subdirectory (or per `*.json` file) under
a source directory and runs the mapping over all of them, writing
`out/<name>.json` per source:

```
python scripts/run_category_mapping_dir.py --api-key YOUR_KEY \
    --source-dir docs/examples/docling --out-dir out
```

A failure on one document (rate limit, malformed response, ...) is logged
and skipped — it doesn't stop the rest of the batch.

## Reading the output

One JSON record per (row, amount column) — "long" format, since documents
have different numbers of amount columns (e.g. 8 fiscal-year/type columns
in one document's table, 1 in another's):

| field             | meaning                                                                 |
|-------------------|--------------------------------------------------------------------------|
| `source`          | the `--source` slug you passed in (e.g. municipality/year)              |
| `table_index`, `row_index` | position in the source document, for tracing back to it        |
| `source_label`    | the row label as docling extracted it (may be noisy/reversed — see below) |
| `matched_code` / `matched_label` | the MoI codebook match, or `null` when no single code applies (see `row_type`) |
| `row_type`        | `"line_item"` (a real leaf budget line), `"subtotal"` (a "סה\"כ ..." row naming one category, e.g. "סה\"כ חינוך" — still gets that category's code), `"grand_total"` (spans multiple categories or isn't one, e.g. "סה\"כ הכנסות", "עודף/גרעון" — `matched_code` is `null`), or `"divider"` (a bare structural row like "הכנסות"/"הוצאות" with no values, never sent to the LLM) |
| `confidence`      | the LLM's 0–1 confidence in the match                                   |
| `note`            | short rationale, or why no code matched                                 |
| `amount_label`    | the column header this value came from (raw text, not yet parsed into year/type) |
| `raw_value`       | the cell text as extracted (e.g. `"9,291"`, `"-"`, `"105.29%"`)          |
| `amount_ils`      | `raw_value` parsed to a number and unit-normalized to whole NIS, or `null` if unparseable (percentages, footnote-ref columns — see Limitations) |
| `unit_status`     | `"explicit"` (document stated its unit), `"inferred"` (LLM guessed from magnitude/context), or `"unresolved"` |
| `unit_multiplier` | `1000`, `1`, or `null` if unresolved                                    |

**Always check `unit_status` before trusting `amount_ils`.** `"inferred"`
means no document text said "thousands" — the LLM guessed from the
numbers' scale and general knowledge of Israeli municipal budget sizes.
That's usually right (a town's total budget can't plausibly be ₪100,000)
but isn't a certainty the way an explicit `"אלפי ש\"ח"` label is.

**Watch for double-counting when summing `amount_ils` by `matched_code`**:
a `"subtotal"` row (e.g. "סה\"כ חינוך") gets the same code as its own
`"line_item"` children (e.g. "שכר עובדי חינוך", "פעולות חינוך"), because
it *is* their sum, not a sibling of them. Summing all rows sharing a code
without filtering `row_type` double-counts. Pick one: sum `"line_item"`
rows yourself, or trust the document's own `"subtotal"`/`"grand_total"`
rows — don't do both.

## Known limitations

- **Hebrew word-order reversal**: docling sometimes reverses word order in
  table cells (e.g. `"המים מפעל"` instead of `"מפעל המים"`). Not fixed here
  — in practice the LLM matches through it fine (e.g. it still correctly
  matched code `41` for that exact reversed label), reflected in a lower
  `confidence` when it's less sure.
- **Column semantics aren't classified**: every non-label column is treated
  as an amount. Percentage columns and footnote-reference-number columns
  (seen in `even_yehuda_2025`) get `amount_ils=None` if they contain `%` or
  letters, but a lone small integer (a footnote ref, e.g. `"2"`) still
  parses as a tiny bogus amount. Visible and low-severity, not corrected.
- **No fiscal-year/amount-type parsing**: `amount_label` is the raw column
  header text; turning `"ביצוע 2024 מחירים שוטפים"` into a structured
  `(fiscal_year=2024, amount_type=actual)` is future work.
- **Codebook suffix codes not parsed**: `scripts/parse_codebook.py` only
  covers the main hierarchical codes (PDF pages 2–12). Pages 13–15
  ("סיומות סעיפי תקבולים/תשלומים", a separate 1–2 digit suffix-code
  catalog) are out of scope.
