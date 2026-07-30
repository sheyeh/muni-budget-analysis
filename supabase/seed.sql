-- Mock/fixture data for dev tables. Applied live to the dev project via
-- the REST API (see PR description); this file makes the same data
-- reviewable and reproducible (e.g. via `supabase db reset` locally).
-- classification_code rows are a small real slice of
-- pipeline/analysis/moi_budget_codes.json (parsed MOI codebook), not the
-- full 672-code import (separate real work, see ADR-0004).

-- muni
insert into muni (muni_id, name_he, name_en, authority_type, district, socioeconomic_cluster, population) values
    (901, 'כפר הדוגמה', 'Kfar HaDugma (sample)', 'local council', 'מרכז', 5, 12000),
    (902, 'עיריית מבחן', 'Mivchan City (sample)', 'city', 'צפון', 7, 85000),
    (903, 'המועצה האזורית לדוגמה', 'Example Regional Council', 'regional council', 'דרום', 4, 25000);

-- classification_code (parent-before-child)
insert into classification_code (code, parent_code, level, category, standard_label_he) values
    ('1', null, 1, 'income', 'מיסים ומענק כללי'),
    ('6', null, 1, 'expense', 'הנהלה כללית'),
    ('11', '1', 2, 'income', 'ארנונות'),
    ('61', '6', 2, 'expense', 'מינהל כללי'),
    ('111', '11', 3, 'income', 'ארנונה כללית'),
    ('611', '61', 3, 'expense', 'הנהלה ומועצה'),
    ('613', '61', 3, 'expense', 'מזכירות'),
    ('1111', '111', 4, 'income', 'ארנונה כללית למגורים- גביה שוטפת'),
    ('1112', '111', 4, 'income', 'ארנונה כללית למגורים- גביה מיתרת פיגורים'),
    ('6111', '611', 4, 'expense', 'ראש הרשות המקומית וסגניו'),
    ('6112', '611', 4, 'expense', 'מועצת הרשות');

-- budget
insert into budget (muni_id, fiscal_year, status, unit, source_ref, processed_at) values
    (901, 2023, 'processed_success', 'thousands_nis', 'processed/901/example_budget_2023/manifest.json', '2026-01-15T10:00:00Z'),
    (901, 2024, 'pending', null, null, null),
    (902, 2023, 'processed_partial', 'thousands_nis', 'processed/902/example_budget_2023/manifest.json', '2026-02-01T09:30:00Z'),
    (902, 2024, 'not_found', null, null, null),
    (903, 2023, 'processed_success', 'nis', 'processed/903/example_budget_2023/manifest.json', '2026-01-20T14:00:00Z'),
    (903, 2024, 'processed_success', 'nis', 'processed/903/example_budget_2024/manifest.json', '2026-03-05T11:15:00Z');

-- budget_line_item (budget_id resolved via subquery, not a hardcoded id)
insert into budget_line_item (budget_id, muni_id, classification_code, row_type, raw_label_he, category, fiscal_year_value, amount_type, amount) values
    ((select id from budget where muni_id = 901 and fiscal_year = 2023), 901, '1111', 'line_item', 'ארנונה כללית למגורים- גביה שוטפת', 'income', 2023, 'budgeted', 4200),
    ((select id from budget where muni_id = 901 and fiscal_year = 2023), 901, '1111', 'line_item', 'ארנונה כללית למגורים- גביה שוטפת', 'income', 2023, 'actual_current_prices', 4150),
    ((select id from budget where muni_id = 901 and fiscal_year = 2023), 901, '1111', 'line_item', 'ארנונה כללית למגורים- גביה שוטפת', 'income', 2023, 'actual_adjusted_prices', 4300),
    ((select id from budget where muni_id = 901 and fiscal_year = 2023), 901, '1111', 'line_item', 'ארנונה כללית למגורים- גביה שוטפת', 'income', 2023, 'execution_pct', 98.8),
    ((select id from budget where muni_id = 901 and fiscal_year = 2023), 901, '1111', 'line_item', 'ארנונה כללית למגורים- גביה שוטפת', 'income', 2023, 'change', 3.5),
    ((select id from budget where muni_id = 901 and fiscal_year = 2023), 901, '1112', 'line_item', 'ארנונה כללית למגורים- גביה מיתרת פיגורים', 'income', 2023, 'budgeted', 180),
    ((select id from budget where muni_id = 901 and fiscal_year = 2023), 901, '111', 'subtotal', 'סה"כ ארנונה כללית', 'income', 2023, 'budgeted', 4380),
    ((select id from budget where muni_id = 901 and fiscal_year = 2023), 901, null, 'grand_total', 'סה"כ הכנסות', 'income', 2023, 'budgeted', 15200),
    ((select id from budget where muni_id = 901 and fiscal_year = 2023), 901, '6111', 'line_item', 'ראש הרשות המקומית וסגניו', 'expense', 2023, 'budgeted', 850),
    ((select id from budget where muni_id = 901 and fiscal_year = 2023), 901, '6112', 'line_item', 'מועצת הרשות', 'expense', 2023, 'budgeted', 220),
    ((select id from budget where muni_id = 901 and fiscal_year = 2023), 901, '611', 'subtotal', 'סה"כ הנהלה ומועצה', 'expense', 2023, 'budgeted', 1070),
    ((select id from budget where muni_id = 901 and fiscal_year = 2023), 901, '613', 'line_item', 'מזכירות', 'expense', 2023, 'budgeted', 640),
    ((select id from budget where muni_id = 901 and fiscal_year = 2023), 901, null, 'grand_total', 'סה"כ הוצאות', 'expense', 2023, 'budgeted', 15200),
    ((select id from budget where muni_id = 902 and fiscal_year = 2023), 902, '1111', 'line_item', 'ארנונה כללית למגורים- גביה שוטפת', 'income', 2023, 'budgeted', 6100),
    ((select id from budget where muni_id = 902 and fiscal_year = 2023), 902, '1112', 'line_item', 'ארנונה כללית למגורים- גביה מיתרת פיגורים', 'income', 2023, 'budgeted', 300),
    ((select id from budget where muni_id = 902 and fiscal_year = 2023), 902, '111', 'subtotal', 'סה"כ ארנונה כללית', 'income', 2023, 'budgeted', 6400),
    ((select id from budget where muni_id = 902 and fiscal_year = 2023), 902, '6111', 'line_item', 'ראש הרשות המקומית וסגניו', 'expense', 2023, 'budgeted', 1200),
    ((select id from budget where muni_id = 902 and fiscal_year = 2023), 902, '613', 'line_item', 'מזכירות', 'expense', 2023, 'budgeted', 900),
    ((select id from budget where muni_id = 902 and fiscal_year = 2023), 902, null, 'grand_total', 'סה"כ הוצאות', 'expense', 2023, 'budgeted', 21000),
    ((select id from budget where muni_id = 903 and fiscal_year = 2023), 903, '1111', 'line_item', 'ארנונה כללית למגורים- גביה שוטפת', 'income', 2023, 'budgeted', 3800000),
    ((select id from budget where muni_id = 903 and fiscal_year = 2023), 903, '1111', 'line_item', 'ארנונה כללית למגורים- גביה שוטפת', 'income', 2023, 'actual_current_prices', 3750000),
    ((select id from budget where muni_id = 903 and fiscal_year = 2023), 903, null, 'grand_total', 'סה"כ הכנסות', 'income', 2023, 'budgeted', 9600000),
    ((select id from budget where muni_id = 903 and fiscal_year = 2023), 903, '6112', 'line_item', 'מועצת הרשות', 'expense', 2023, 'budgeted', 410000),
    ((select id from budget where muni_id = 903 and fiscal_year = 2023), 903, '613', 'line_item', 'מזכירות', 'expense', 2023, 'budgeted', 350000),
    ((select id from budget where muni_id = 903 and fiscal_year = 2023), 903, null, 'grand_total', 'סה"כ הוצאות', 'expense', 2023, 'budgeted', 9600000),
    ((select id from budget where muni_id = 903 and fiscal_year = 2024), 903, '1111', 'line_item', 'ארנונה כללית למגורים- גביה שוטפת', 'income', 2024, 'budgeted', 4000000),
    ((select id from budget where muni_id = 903 and fiscal_year = 2024), 903, '1112', 'line_item', 'ארנונה כללית למגורים- גביה מיתרת פיגורים', 'income', 2024, 'budgeted', 210000),
    ((select id from budget where muni_id = 903 and fiscal_year = 2024), 903, null, 'grand_total', 'סה"כ הכנסות', 'income', 2024, 'budgeted', 10100000),
    ((select id from budget where muni_id = 903 and fiscal_year = 2024), 903, '611', 'line_item', 'הנהלה ומועצה', 'expense', 2024, 'budgeted', 900000),
    ((select id from budget where muni_id = 903 and fiscal_year = 2024), 903, '613', 'line_item', 'מזכירות', 'expense', 2024, 'budgeted', 360000),
    ((select id from budget where muni_id = 903 and fiscal_year = 2024), 903, null, 'grand_total', 'סה"כ הוצאות', 'expense', 2024, 'budgeted', 10100000);
