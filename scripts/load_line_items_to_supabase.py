"""
scripts/load_line_items_to_supabase.py

Minimal, one-off loader mapping the level-3 spike's existing output
(pipeline/analysis/, docs/examples/level3-analysis/out/*.json) into the
Supabase schema (docs/adr/0004-postgres-supabase-data-model.md,
supabase/migrations/20260730221726_init_schema.sql).

Deliberately NOT the full designed contract in
docs/handshake-level3-postgres.md -- there is no LLM-based category /
amount-type / fiscal-year resolution here (see that doc's "Open questions"
section: the real spike emits raw amount_label text, not a resolved
(fiscal_year_value, amount_type) pair, and has no category field at all).
This script takes what the spike already produces and maps it with
deterministic, best-effort rules, dropping rows it can't confidently
resolve rather than guessing wrong:

  - category: derived from the matched classification code's `side` field
    (pipeline/analysis/moi_budget_codes.json: "receipts" -> income,
    "payments" -> expense). Rows with no matched_code (most grand_total
    rows, and any row the spike's LLM step couldn't match) get no category
    and are DROPPED -- budget_line_item.category is NOT NULL.
  - amount_type: keyword heuristic over the spike's amount_label text (no
    LLM call). Defaults to "budgeted" when the label carries no
    distinguishing keyword (e.g. mate_yehuda_2024's tables, where every
    amount_label is just the unit note "באלפי ש''ח").
  - fiscal_year_value: first 4-digit year found in amount_label, else the
    document's target_year (from level 2.5's scoped.json).
  - amount: amount_ils as-is (the spike already normalizes to whole NIS).
    Rows where it's null (garbled/non-numeric raw values) are DROPPED --
    amount is NOT NULL.

Known, accepted limitation: the spike's amount_label/raw_value split isn't
a clean semantic split (see build_output.py's own docstring) -- e.g.
even_yehuda_2025 has at least one footnote-index column that gets treated
as a value column upstream. Not fixed here (out of scope for "map existing
spike output into the DB").

No live DB connection is available in this checkout (no .env, no Supabase
client library in requirements.txt, no DB-executing MCP tool wired up at
the time this was written). This script's primary output is idempotent SQL
(--sql-out), meant to be pasted into the Supabase SQL editor / run via
`psql` / `supabase db execute`. If `psycopg` is installed and DATABASE_URL
is set, --apply runs the same SQL directly via a raw Postgres connection.

--apply-rest is the path that actually works with Supabase's new-style API
keys (sb_publishable_.../sb_secret_...) -- those are Data API (PostgREST)
keys, not a Postgres connection string, so raw multi-statement SQL (the
--apply path's CTEs) can't run through them. --apply-rest instead does the
same upsert / wholesale-replace semantics as plain REST calls (`requests`,
already a project dependency): upsert classification_code, then per budget:
upsert budget (on_conflict=muni_id,fiscal_year, get back the id), DELETE
existing budget_line_item rows for that id, POST the new ones in batches.
No `muni` writes: the live `muni` table already holds the real municipality
registry with correct rows for every source's real semel-yishuv ID (see
SOURCE_REAL_MUNI_ID below) -- discovered while wiring this up, see
--delete-mock-data for the now-redundant old mock rows this superseded.

Usage:
    python scripts/load_line_items_to_supabase.py --sql-out out/load.sql
    python scripts/load_line_items_to_supabase.py --apply       # needs DATABASE_URL + psycopg installed
    python scripts/load_line_items_to_supabase.py --apply-rest --supabase-url https://xxx.supabase.co --supabase-key sb_secret_...
        # or set SUPABASE_URL / SUPABASE_KEY env vars instead of the flags
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.analysis.codebook import by_code, load_codebook  # noqa: E402

LEVEL2_DIR = REPO_ROOT / "docs" / "examples" / "level2-processing"
LEVEL25_DIR = REPO_ROOT / "docs" / "examples" / "level2.5-scope-filter"
LEVEL3_OUT_DIR = REPO_ROOT / "docs" / "examples" / "level3-analysis" / "out"

# source slug -> synthetic folder id, per docs/examples/level2-processing/*/manifest.json
# and docs/examples/level2.5-scope-filter/*/scoped.json -- used ONLY to locate
# those committed files on disk (CONTEXT.md's "muni_id caveat": 901-910 are
# synthetic placeholders in this repo's examples, not real semel-yishuv codes).
# Only files that actually went through the level-3 spike are here.
# elad_2022 (903) is excluded: excel_native input, the spike only reads
# docling native.json, so it has no line items -- see the plan/PR notes.
SOURCE_FOLDER_ID: dict[str, int] = {
    "even_yehuda_2025": 901,
    "mate_yehuda_2024": 902,
    "elyakin_2026": 906,
    "gezer_2026": 907,
    "jaljulya_2026": 908,
    "jerusalem_2026": 909,
    "lachish_2026": 910,
}

# source slug -> REAL semel-yishuv muni_id. The live Supabase `muni` table
# turned out to already hold the full real municipality registry (discovered
# while wiring up --apply-rest) -- so budget/budget_line_item rows use the
# real ID, not the synthetic folder id above, per CONTEXT.md's "Muni ID" rule
# (reuse the real external identifier rather than inventing a project one).
# No muni-table write is needed for these: the real rows already exist with
# correct names.
SOURCE_REAL_MUNI_ID: dict[str, int] = {
    "even_yehuda_2025": 60182,
    "mate_yehuda_2024": 1026,
    "elyakin_2026": 60041,
    "gezer_2026": 4330,
    "jerusalem_2026": 13000,
    "lachish_2026": 6150,
}

YEAR_RE = re.compile(r"(19|20)\d{2}")


def sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def sql_value(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    return sql_str(str(value))


def derive_category(matched_code: str | None, codebook_by_code: dict[str, dict]) -> str | None:
    if not matched_code:
        return None
    entry = codebook_by_code.get(matched_code)
    if not entry:
        return None
    return "income" if entry.get("side") == "receipts" else "expense"


def derive_amount_type(amount_label: str) -> str:
    label = amount_label or ""
    has_execution = "ביצוע" in label
    has_adjusted = "מקודם" in label or "למחיר" in label
    if has_execution and has_adjusted:
        return "actual_adjusted_prices"
    if has_execution:
        return "actual_current_prices"
    if "תקציב" in label:
        return "budgeted"
    if "%" in label or "אחוז" in label:
        return "execution_pct"
    if "שינוי" in label or "הפרש" in label:
        return "change"
    return "budgeted"  # default: empty / unit-only labels, single-value documents


def derive_fiscal_year_value(amount_label: str, target_year: int) -> int:
    match = YEAR_RE.search(amount_label or "")
    return int(match.group(0)) if match else target_year


def load_manifest(muni_id: int) -> dict:
    return json.loads((LEVEL2_DIR / str(muni_id) / "manifest.json").read_text(encoding="utf-8"))


def load_scoped(muni_id: int) -> dict:
    return json.loads((LEVEL25_DIR / str(muni_id) / "scoped.json").read_text(encoding="utf-8"))


def load_spike_output(source: str) -> list[dict]:
    return json.loads((LEVEL3_OUT_DIR / f"{source}.json").read_text(encoding="utf-8"))


def build_line_items(
    records: list[dict], target_year: int, codebook_by_code: dict[str, dict]
) -> tuple[list[dict], int]:
    """Returns (kept line items, skipped count)."""
    kept: list[dict] = []
    skipped = 0
    for rec in records:
        if rec["row_type"] == "divider":
            continue  # should already be excluded by the spike; defensive
        category = derive_category(rec.get("matched_code"), codebook_by_code)
        if category is None:
            skipped += 1
            continue
        if rec.get("amount_ils") is None:
            skipped += 1
            continue
        amount_label = rec.get("amount_label") or ""
        kept.append(
            {
                "classification_code": rec.get("matched_code"),
                "row_type": rec["row_type"],
                "raw_label_he": rec["source_label"],
                "category": category,
                "fiscal_year_value": derive_fiscal_year_value(amount_label, target_year),
                "amount_type": derive_amount_type(amount_label),
                "amount": rec["amount_ils"],
            }
        )
    return kept, skipped


def render_classification_code_sql(rows: list[dict]) -> str:
    lines = [f"-- classification_code: full MOI codebook ({len(rows)} entries)"]
    for r in rows:
        lines.append(
            "INSERT INTO classification_code (code, parent_code, level, category, standard_label_he) "
            f"VALUES ({sql_value(r['code'])}, {sql_value(r['parent_code'])}, "
            f"{sql_value(r['level'])}, {sql_value(r['category'])}, {sql_value(r['standard_label_he'])}) "
            "ON CONFLICT (code) DO UPDATE SET parent_code = excluded.parent_code, "
            "level = excluded.level, category = excluded.category, "
            "standard_label_he = excluded.standard_label_he;"
        )
    return "\n".join(lines)


def render_budget_and_line_items_sql(
    muni_id: int, fiscal_year: int, status: str, source_ref: str, line_items: list[dict]
) -> str:
    processed_at = datetime.now(timezone.utc).isoformat()
    values_rows = ", ".join(
        "("
        + ", ".join(
            [
                sql_value(li["classification_code"]),
                sql_value(li["row_type"]),
                sql_value(li["raw_label_he"]),
                sql_value(li["category"]),
                sql_value(li["fiscal_year_value"]),
                sql_value(li["amount_type"]),
                sql_value(li["amount"]),
            ]
        )
        + ")"
        for li in line_items
    )
    return f"""-- budget + budget_line_item for muni_id={muni_id}, fiscal_year={fiscal_year}
WITH b AS (
    INSERT INTO budget (muni_id, fiscal_year, status, unit, source_ref, processed_at)
    VALUES ({muni_id}, {fiscal_year}, {sql_value(status)}, 'nis', {sql_value(source_ref)}, {sql_value(processed_at)})
    ON CONFLICT (muni_id, fiscal_year) DO UPDATE SET
        status = excluded.status, unit = excluded.unit,
        source_ref = excluded.source_ref, processed_at = excluded.processed_at
    RETURNING id
), del AS (
    DELETE FROM budget_line_item WHERE budget_id = (SELECT id FROM b)
)
INSERT INTO budget_line_item
    (budget_id, muni_id, classification_code, row_type, raw_label_he, category, fiscal_year_value, amount_type, amount)
SELECT b.id, {muni_id}, v.classification_code, v.row_type, v.raw_label_he, v.category, v.fiscal_year_value, v.amount_type, v.amount
FROM b, (VALUES {values_rows}) AS v(classification_code, row_type, raw_label_he, category, fiscal_year_value, amount_type, amount);
"""


def build_all_data(sources: list[str]) -> tuple[dict, list[str]]:
    """Structured form of the same data build_all_sql renders to SQL text --
    used by the REST-apply path, which needs rows/dicts, not SQL strings.

    No `muni` rows here: the live `muni` table turned out to already hold the
    real municipality registry (discovered wiring up --apply-rest) with
    correct names for every SOURCE_REAL_MUNI_ID -- nothing to upsert there."""
    codebook = load_codebook()
    codebook_by_code = by_code(codebook)

    warnings: list[str] = []
    classification_code_rows = [
        {
            "code": entry["code"],
            "parent_code": entry.get("parent"),
            "level": entry["level"],
            "category": "income" if entry.get("side") == "receipts" else "expense",
            "standard_label_he": entry["label"],
        }
        for entry in sorted(codebook, key=lambda e: e["level"])
    ]

    budgets = []
    for source in sources:
        folder_id = SOURCE_FOLDER_ID[source]
        real_muni_id = SOURCE_REAL_MUNI_ID[source]
        manifest = load_manifest(folder_id)
        if manifest.get("status") == "failed":
            warnings.append(f"{source}: manifest status=failed, skipping entirely")
            continue
        scoped = load_scoped(folder_id)
        target_year = scoped["target_year"]
        records = load_spike_output(source)

        line_items, skipped = build_line_items(records, target_year, codebook_by_code)
        if not line_items:
            warnings.append(f"{source}: 0 line items survived filtering, skipping budget/line-item insert")
            continue
        status = "processed_success" if skipped == 0 else "processed_partial"
        if skipped:
            warnings.append(f"{source}: {skipped}/{len(records)} spike records dropped (no category or no amount)")

        source_ref = str(
            (LEVEL2_DIR / str(folder_id) / "manifest.json").relative_to(REPO_ROOT)
        ).replace("\\", "/")
        budgets.append(
            {
                "muni_id": real_muni_id,
                "fiscal_year": target_year,
                "status": status,
                "unit": "nis",
                "source_ref": source_ref,
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "line_items": line_items,
            }
        )

    data = {"classification_code": classification_code_rows, "budgets": budgets}
    return data, warnings


def apply_via_rest(data: dict, base_url: str, api_key: str) -> None:
    import requests

    base_url = base_url.rstrip("/")
    headers = {
        "apikey": api_key,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    def upsert(table: str, rows: list[dict], on_conflict: str, chunk_size: int = 200) -> None:
        params = {"on_conflict": on_conflict}
        req_headers = {**headers, "Prefer": "resolution=merge-duplicates"}
        for i in range(0, len(rows), chunk_size):
            chunk = rows[i : i + chunk_size]
            resp = requests.post(
                f"{base_url}/rest/v1/{table}", params=params, headers=req_headers, json=chunk, timeout=60
            )
            if not resp.ok:
                raise RuntimeError(f"upsert {table} failed ({resp.status_code}): {resp.text[:500]}")
        print(f"  upserted {len(rows)} rows into {table}")

    upsert("classification_code", data["classification_code"], on_conflict="code")

    for budget in data["budgets"]:
        budget_row = {k: v for k, v in budget.items() if k != "line_items"}
        resp = requests.post(
            f"{base_url}/rest/v1/budget",
            params={"on_conflict": "muni_id,fiscal_year"},
            headers={**headers, "Prefer": "resolution=merge-duplicates,return=representation"},
            json=[budget_row],
            timeout=60,
        )
        if not resp.ok:
            raise RuntimeError(f"upsert budget failed ({resp.status_code}): {resp.text[:500]}")
        budget_id = resp.json()[0]["id"]

        resp = requests.delete(
            f"{base_url}/rest/v1/budget_line_item",
            params={"budget_id": f"eq.{budget_id}"},
            headers=headers,
            timeout=60,
        )
        if not resp.ok:
            raise RuntimeError(f"delete budget_line_item failed ({resp.status_code}): {resp.text[:500]}")

        line_item_rows = [{**li, "budget_id": budget_id, "muni_id": budget["muni_id"]} for li in budget["line_items"]]
        chunk_size = 500
        for i in range(0, len(line_item_rows), chunk_size):
            chunk = line_item_rows[i : i + chunk_size]
            resp = requests.post(
                f"{base_url}/rest/v1/budget_line_item", headers=headers, json=chunk, timeout=120
            )
            if not resp.ok:
                raise RuntimeError(f"insert budget_line_item failed ({resp.status_code}): {resp.text[:500]}")
        print(
            f"  muni_id={budget['muni_id']} fiscal_year={budget['fiscal_year']}: "
            f"budget_id={budget_id}, {len(line_item_rows)} line items"
        )


def build_all_sql(sources: list[str]) -> tuple[str, list[str]]:
    data, warnings = build_all_data(sources)
    parts = [render_classification_code_sql(data["classification_code"])]
    for budget in data["budgets"]:
        parts.append(
            render_budget_and_line_items_sql(
                budget["muni_id"], budget["fiscal_year"], budget["status"], budget["source_ref"], budget["line_items"]
            )
        )
    return "\n\n".join(parts) + "\n", warnings


# Old mock/fixture data (supabase/seed.sql), predating the real muni registry
# discovered while wiring up --apply-rest -- now redundant/confusing since the
# real munis for these same places (Even Yehuda, Mate Yehuda, Elad) exist
# under their real semel-yishuv IDs. budget has ON DELETE CASCADE to
# budget_line_item, so deleting `budget` rows is enough to clean both.
MOCK_MUNI_IDS = (901, 902, 903)


def delete_mock_data(base_url: str, api_key: str) -> None:
    import requests

    base_url = base_url.rstrip("/")
    headers = {"apikey": api_key, "Authorization": f"Bearer {api_key}"}
    id_list = ",".join(str(m) for m in MOCK_MUNI_IDS)

    resp = requests.delete(
        f"{base_url}/rest/v1/budget", params={"muni_id": f"in.({id_list})"}, headers=headers, timeout=60
    )
    if not resp.ok:
        raise RuntimeError(f"delete mock budget rows failed ({resp.status_code}): {resp.text[:500]}")
    resp = requests.delete(
        f"{base_url}/rest/v1/muni", params={"muni_id": f"in.({id_list})"}, headers=headers, timeout=60
    )
    if not resp.ok:
        raise RuntimeError(f"delete mock muni rows failed ({resp.status_code}): {resp.text[:500]}")
    print(f"Deleted mock muni/budget/budget_line_item rows for muni_id in {MOCK_MUNI_IDS}")


def apply_sql(sql: str) -> None:
    import os

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("--apply requires DATABASE_URL to be set (no local .env in this checkout).", file=sys.stderr)
        sys.exit(1)
    try:
        import psycopg
    except ImportError:
        print(
            "--apply requires the 'psycopg' package (not in requirements.txt -- "
            "install it separately, e.g. `pip install 'psycopg[binary]'`).",
            file=sys.stderr,
        )
        sys.exit(1)

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    print("Applied.")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--sources",
        nargs="*",
        default=list(SOURCE_FOLDER_ID.keys()),
        help="source slugs to load (default: all with committed level-3 spike output)",
    )
    p.add_argument("--sql-out", help="write generated SQL to this file")
    p.add_argument("--apply", action="store_true", help="execute the SQL via DATABASE_URL (needs psycopg)")
    p.add_argument(
        "--apply-rest",
        action="store_true",
        help="apply via the Supabase REST/PostgREST API instead of raw SQL (needs --supabase-url/--supabase-key or SUPABASE_URL/SUPABASE_KEY env vars)",
    )
    p.add_argument("--supabase-url", default=None, help="e.g. https://xxxx.supabase.co (or set SUPABASE_URL)")
    p.add_argument("--supabase-key", default=None, help="Data API key (or set SUPABASE_KEY)")
    p.add_argument(
        "--delete-mock-data",
        action="store_true",
        help=f"also delete the old mock muni/budget/budget_line_item rows for muni_id in {MOCK_MUNI_IDS} (needs --apply-rest creds)",
    )
    return p.parse_args()


def main() -> None:
    import os

    args = parse_args()
    unknown = [s for s in args.sources if s not in SOURCE_FOLDER_ID]
    if unknown:
        print(f"Unknown source(s), not in SOURCE_FOLDER_ID: {unknown}", file=sys.stderr)
        sys.exit(1)

    if args.apply_rest or args.delete_mock_data:
        base_url = args.supabase_url or os.environ.get("SUPABASE_URL")
        api_key = args.supabase_key or os.environ.get("SUPABASE_KEY")
        if not base_url or not api_key:
            print("--apply-rest/--delete-mock-data require --supabase-url/--supabase-key or SUPABASE_URL/SUPABASE_KEY env vars.", file=sys.stderr)
            sys.exit(1)
        if args.delete_mock_data:
            delete_mock_data(base_url, api_key)
        if args.apply_rest:
            data, warnings = build_all_data(args.sources)
            for w in warnings:
                print(f"WARNING: {w}", file=sys.stderr)
            apply_via_rest(data, base_url, api_key)
        return

    sql, warnings = build_all_sql(args.sources)

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    if args.sql_out:
        out_path = Path(args.sql_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(sql, encoding="utf-8")
        print(f"Wrote SQL to {out_path}")

    if args.apply:
        apply_sql(sql)
    elif not args.sql_out:
        print(sql)


if __name__ == "__main__":
    main()
