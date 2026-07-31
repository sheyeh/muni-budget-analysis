-- Schema per docs/handshake-level3-postgres.md (rationale: docs/adr/0004-postgres-supabase-data-model.md)

-- muni: dimension, ~200-250 rows, static
create table muni (
    muni_id integer primary key, -- semel yishuv, reused as-is
    name_he text not null,
    name_en text,
    authority_type text not null, -- city / local council / regional council
    district text,
    socioeconomic_cluster smallint, -- אשכול, 1-10
    population integer
);

-- classification_code: dimension, shared taxonomy, self-referencing hierarchy
create table classification_code (
    code text primary key,
    parent_code text references classification_code (code),
    level smallint not null,
    category text not null check (category in ('income', 'expense')),
    standard_label_he text not null
);

create index classification_code_parent_code_idx on classification_code (parent_code);

-- budget: one row per muni x attempted fiscal year
create table budget (
    id bigint generated always as identity primary key,
    muni_id integer not null references muni (muni_id),
    fiscal_year integer not null,
    status text not null check (status in ('pending', 'processed_success', 'processed_partial', 'processed_failed', 'not_found')),
    unit text, -- currency/scale for every line item in this document, e.g. 'thousands_nis' | 'nis'
    source_ref text, -- pointer to processed/{muni_id}/{filename_stem}/manifest.json
    processed_at timestamptz,
    unique (muni_id, fiscal_year)
);

-- budget_line_item: fact table, long/tidy (one row per classification_code x fiscal_year_value x amount_type)
create table budget_line_item (
    id bigint generated always as identity primary key,
    budget_id bigint not null references budget (id) on delete cascade,
    muni_id integer not null references muni (muni_id), -- denormalized from budget, avoids join for the dominant query shape
    classification_code text references classification_code (code), -- nullable: subtotal/header rows, or no explicit code
    row_type text not null check (row_type in ('line_item', 'subtotal', 'grand_total', 'divider')),
    raw_label_he text not null,
    category text not null check (category in ('income', 'expense')),
    fiscal_year_value integer not null,
    amount_type text not null check (amount_type in ('budgeted', 'actual_current_prices', 'actual_adjusted_prices', 'execution_pct', 'change')),
    amount numeric not null
);

create index budget_line_item_budget_id_idx on budget_line_item (budget_id);
create index budget_line_item_muni_category_year_idx on budget_line_item (muni_id, classification_code, fiscal_year_value);
