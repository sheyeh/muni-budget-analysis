// Live Supabase integration. Fetches the 3 real DB municipalities (901/902/903 — explicitly
// sample data per their own name_he/name_en fields) and reshapes them into the same schema the
// static site-data/*.json files use, so page-map.js/page-category.js/page-authority.js don't need
// to know or care whether a given municipality came from disk or from the DB.
//
// Real, honest limitations of this DB (checked directly via REST, no schema doc existed):
// - `budget.status` is a coarse enum (processed_success/processed_partial/pending/not_found) with
//   no XLS/narrative-explanation flags, so the score's +3/+2 bonuses can never apply to DB-sourced
//   municipalities — only the base 0/7/15. This is a real data gap, not a bug in this code.
// - Category coverage: `budget_line_item`'s classification_codes in this sample only cover MoI
//   code 61 (מינהל כללי) — no education/welfare/sanitation/etc. line items exist in the DB at all.
//   Page 2/3 will only ever show that one category for these municipalities until more is loaded.
const DbData = (() => {
  const SUPABASE_URL = "https://eyimyaznvtwataqniinc.supabase.co";
  const SUPABASE_ANON_KEY = "sb_publishable_EfmOSiqflmh3cEprA1A7Sg_k2hCKJOk";

  const YEARS = [2026, 2025, 2024, 2023, 2022];
  const TYPE_HE = { "local council": "מועצה מקומית", city: "עיריה", "regional council": "מועצה אזורית", unknown: "לא ידוע" };
  const UNIT_MULTIPLIER = { nis: 1, thousands_nis: 1000 };
  const STATUS_MAP = {
    processed_success: "detailed",
    processed_partial: "summary",
    not_found: "missing",
    pending: "not_checked",
  };
  const CATEGORY_61_LABEL = "מינהל כללי";

  async function fetchTable(name, query) {
    const res = await fetch(`${SUPABASE_URL}/rest/v1/${name}?${query}`, {
      headers: { apikey: SUPABASE_ANON_KEY, Authorization: `Bearer ${SUPABASE_ANON_KEY}` },
    });
    if (!res.ok) throw new Error(`Supabase fetch failed for ${name}: ${res.status}`);
    return res.json();
  }

  function yearPoints(status) {
    // No is_xls/has_explanation signal exists in this DB — bonuses are always 0 here.
    return { missing: 0, summary: 7, detailed: 15 }[status] ?? 0;
  }

  function buildYears(muniId, budgetRows) {
    const byYear = new Map(budgetRows.filter((b) => b.muni_id === muniId).map((b) => [b.fiscal_year, b]));
    return YEARS.map((year) => {
      const b = byYear.get(year);
      if (!b) return { year, status: "not_checked", item_count: null, format: null, is_xls: null, has_explanation: null, source_url: null };
      const status = STATUS_MAP[b.status] || "not_checked";
      return {
        year,
        status,
        item_count: null, // filled in by caller once line items are known
        format: null, // not tracked in this DB
        is_xls: status === "not_checked" ? null : false,
        has_explanation: status === "not_checked" ? null : false,
        source_url: null, // budget.source_ref is a relative pipeline path, not a fetchable URL
      };
    });
  }

  function computeScore(years) {
    const checked = years.filter((y) => y.status !== "not_checked");
    if (!checked.length) return { score: null, checkedYearsCount: 0 };
    const sum = checked.reduce((acc, y) => acc + yearPoints(y.status), 0);
    return { score: Math.round((100 * sum) / (20 * checked.length)), checkedYearsCount: checked.length };
  }

  // Sample data is structurally messy (e.g. code 611 shows up as a "subtotal" for one municipality
  // but a plain "line_item" for another) — this reconciles both shapes rather than assuming one.
  function code61Total(rows) {
    const r611 = rows.filter((r) => r.classification_code === "611");
    const subtotal611 = r611.find((r) => r.row_type === "subtotal");
    const direct611 = r611.find((r) => r.row_type === "line_item");
    const r6111 = rows.find((r) => r.classification_code === "6111");
    const r6112 = rows.find((r) => r.classification_code === "6112");
    const r613 = rows.find((r) => r.classification_code === "613");
    let admin611;
    if (subtotal611) admin611 = subtotal611.amount;
    else if (direct611) admin611 = direct611.amount;
    else admin611 = (r6111 ? r6111.amount : 0) + (r6112 ? r6112.amount : 0);
    return admin611 + (r613 ? r613.amount : 0);
  }

  async function fetchAll() {
    const [munis, budgets, lineItems] = await Promise.all([
      fetchTable("muni", "select=*"),
      fetchTable("budget", "select=*"),
      fetchTable("budget_line_item", "select=*&amount_type=eq.budgeted"),
    ]);

    const municipalities = [];
    const authorityAll = {};
    const category61ByMuni = {};

    for (const m of munis) {
      const muniId = String(m.muni_id);
      const years = buildYears(m.muni_id, budgets);

      // item_count per year = distinct expense line_items that year (matches out/*.json's convention).
      for (const y of years) {
        if (y.status === "not_checked") continue;
        const count = lineItems.filter(
          (li) => li.muni_id === m.muni_id && li.fiscal_year_value === y.year && li.row_type === "line_item" && li.category === "expense"
        ).length;
        y.item_count = count || null;
      }

      const { score, checkedYearsCount } = computeScore(years);

      const budgetForMuni = budgets.filter((b) => b.muni_id === m.muni_id).sort((a, b) => b.fiscal_year - a.fiscal_year);
      const unit = budgetForMuni.length ? UNIT_MULTIPLIER[budgetForMuni[0].unit] || 1 : 1;
      const latestGrandTotal = lineItems.find(
        (li) => li.muni_id === m.muni_id && li.row_type === "grand_total" && li.category === "expense" && li.fiscal_year_value === (budgetForMuni[0] && budgetForMuni[0].fiscal_year)
      );

      municipalities.push({
        muni_id: muniId,
        name: m.name_he,
        type: TYPE_HE[m.authority_type] || m.authority_type,
        population: m.population,
        cluster: m.socioeconomic_cluster,
        latest_budget_ils: latestGrandTotal ? latestGrandTotal.amount * unit : null,
        website_url: null,
        has_pipeline_data: checkedYearsCount > 0,
        years,
        latest_format: null,
        checked_years_count: checkedYearsCount,
        transparency_score: score,
        source: "db", // marks this entry as live-fetched, for anyone inspecting the merged data
      });

      // Category 61 values, per year that has expense line items.
      const yearsWithData = [...new Set(lineItems.filter((li) => li.muni_id === m.muni_id && li.category === "expense").map((li) => li.fiscal_year_value))];
      const byYear = {};
      for (const year of yearsWithData) {
        const rowsThisYear = lineItems.filter((li) => li.muni_id === m.muni_id && li.fiscal_year_value === year && li.category === "expense");
        const total = code61Total(rowsThisYear);
        const budgetRow = budgetForMuni.find((b) => b.fiscal_year === year);
        const yearUnit = budgetRow ? UNIT_MULTIPLIER[budgetRow.unit] || 1 : 1;
        const total_ils = total * yearUnit;
        const grandTotal = lineItems.find((li) => li.muni_id === m.muni_id && li.fiscal_year_value === year && li.row_type === "grand_total" && li.category === "expense");
        byYear[year] = {
          total_ils,
          pct_of_budget: grandTotal ? Math.round((total_ils / (grandTotal.amount * yearUnit)) * 1000) / 1000 : null,
          per_capita: m.population ? Math.round(total_ils / m.population) : null,
        };
      }
      if (Object.keys(byYear).length) category61ByMuni[muniId] = byYear;

      // Authority bundle: treemap/pie/trend built from the same code-61 rows, real codebook labels.
      if (Object.keys(byYear).length) {
        const latestYear = Math.max(...Object.keys(byYear).map(Number));
        const rowsLatest = lineItems.filter((li) => li.muni_id === m.muni_id && li.fiscal_year_value === latestYear && li.category === "expense");
        const rootLabel = `תקציב ${m.name_he}`;
        const labels = [rootLabel, CATEGORY_61_LABEL];
        const parents = ["", rootLabel];
        const values_total = [null, byYear[latestYear].total_ils];
        const values_pct_of_budget = [null, byYear[latestYear].pct_of_budget];
        const values_per_capita = [null, byYear[latestYear].per_capita];
        for (const r of rowsLatest) {
          if (r.classification_code === "611" && r.row_type === "subtotal") continue; // already the 611 branch total below
          if (!["611", "6111", "6112", "613"].includes(r.classification_code)) continue;
          labels.push(r.raw_label_he);
          parents.push(CATEGORY_61_LABEL);
          values_total.push(r.amount * unit);
          values_pct_of_budget.push(null);
          values_per_capita.push(null);
        }

        authorityAll[muniId] = {
          muni_id: muniId,
          name: m.name_he,
          has_pipeline_data: true,
          website_url: null,
          treemap: { labels, parents, values_total, values_pct_of_budget, values_per_capita },
          pie_latest_year: {
            year: latestYear,
            slices: [{ code: "61", label: CATEGORY_61_LABEL, total_ils: byYear[latestYear].total_ils, pct: byYear[latestYear].pct_of_budget }],
          },
          trend: {
            years: YEARS.slice().sort((a, b) => a - b),
            series: [
              {
                code: "61",
                label: CATEGORY_61_LABEL,
                total_ils: YEARS.slice().sort((a, b) => a - b).map((y) => (byYear[y] ? byYear[y].total_ils : null)),
                pct_of_budget: YEARS.slice().sort((a, b) => a - b).map((y) => (byYear[y] ? byYear[y].pct_of_budget : null)),
                per_capita: YEARS.slice().sort((a, b) => a - b).map((y) => (byYear[y] ? byYear[y].per_capita : null)),
              },
            ],
          },
          source_files: years.filter((y) => y.status !== "not_checked").map((y) => ({ year: y.year, status: y.status, url: null })),
        };
      } else {
        authorityAll[muniId] = {
          muni_id: muniId,
          name: m.name_he,
          has_pipeline_data: false,
          website_url: null,
          treemap: { labels: [], parents: [], values_total: [], values_pct_of_budget: [], values_per_capita: [] },
          pie_latest_year: { year: null, slices: [] },
          trend: { years: [], series: [] },
          source_files: years.filter((y) => y.status !== "not_checked").map((y) => ({ year: y.year, status: y.status, url: null })),
        };
      }
    }

    return { municipalities, category61ByMuni, authorityAll };
  }

  return { fetchAll };
})();
