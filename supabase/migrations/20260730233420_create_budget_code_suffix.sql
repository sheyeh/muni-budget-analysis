-- budget_code_suffix: dimension, orthogonal 1-3 digit suffix-code catalog appended to a
-- base classification_code to form a full account number (see scripts/parse_codebook.py).
-- Keyed by (side, suffix_code), not suffix_code alone: suffix codes reuse the same 1-9
-- digits independently per side and collide with main-tree classification_code strings.
create table budget_code_suffix (
    side text not null check (side in ('payments', 'receipts')),
    suffix_code text not null,
    parent_suffix_code text, -- self-referencing within same side; NOT FK-enforced -- see note below
    level smallint not null,
    label_he text not null,
    source_page integer not null,
    primary key (side, suffix_code)
);

create index budget_code_suffix_parent_idx on budget_code_suffix (side, parent_suffix_code);

-- Known source gap (verified against pipeline/analysis/moi_budget_code_suffixes.json):
-- 7 rows reference a parent_suffix_code with no corresponding row (payments 00/01/39/49,
-- receipts level-1 "2"). Real gaps in the parsed codebook, not a loader bug -- this is why
-- parent_suffix_code has no FK, unlike classification_code.parent_code.
