// One-off generator for web/site-data mock JSON (Phase 0). Not part of the app; run once with
// `node scripts/_gen_mock_ui_data.js` then delete or leave as a reference for regenerating mocks.
const fs = require("fs");
const path = require("path");

const OUT_DIR = path.join(__dirname, "..", "web", "site-data");

const YEARS = [2026, 2025, 2024, 2023, 2022];

function yearPoints(status, isXls, hasExpl) {
  const base = { missing: 0, summary: 7, detailed: 15 }[status];
  if (status === "missing") return base;
  return base + (isXls ? 3 : 0) + (hasExpl ? 2 : 0);
}

function buildYears(checked) {
  // checked: array of {year, status, format, isXls, hasExpl, itemCount}
  const byYear = new Map(checked.map((c) => [c.year, c]));
  return YEARS.map((year) => {
    const c = byYear.get(year);
    if (!c) {
      return { year, status: "not_checked", item_count: null, format: null, is_xls: null, has_explanation: null, source_url: null };
    }
    return {
      year,
      status: c.status,
      item_count: c.status === "missing" ? null : c.itemCount,
      format: c.status === "missing" ? null : c.format,
      is_xls: c.status === "missing" ? null : !!c.isXls,
      has_explanation: c.status === "missing" ? null : !!c.hasExpl,
      source_url: null,
    };
  });
}

function computeScore(checked) {
  const checkedYears = checked.filter((c) => c.status !== "not_checked");
  const n = checkedYears.length;
  if (n === 0) return { score: null, checkedYearsCount: 0 };
  const sum = checkedYears.reduce((acc, c) => acc + yearPoints(c.status, c.isXls, c.hasExpl), 0);
  const score = Math.round((100 * sum) / (20 * n));
  return { score, checkedYearsCount: n };
}

function latestFormat(checked) {
  const sorted = [...checked].filter((c) => c.status !== "missing" && c.status !== "not_checked").sort((a, b) => b.year - a.year);
  return sorted.length ? sorted[0].format : null;
}

// Raw roster: [name, type, muni_id, cluster, population, latest_budget_ils, website_url, checkedYears[]]
const ROSTER = [
  ["תל אביב-יפו", "עיריה", "5000", 8, 460613, 12000000000, "https://www.tel-aviv.gov.il", [
    { year: 2025, status: "detailed", format: "xlsx", isXls: true, hasExpl: true, itemCount: 340 },
    { year: 2024, status: "detailed", format: "xlsx", isXls: true, hasExpl: false, itemCount: 322 },
    { year: 2023, status: "detailed", format: "pdf_generated", isXls: false, hasExpl: false, itemCount: 340 },
  ]],
  ["ירושלים", "עיריה", "3000", 4, 986000, 9000000000, "https://www.jerusalem.muni.il", [
    { year: 2025, status: "summary", format: "pdf_generated", isXls: false, hasExpl: false, itemCount: 6 },
    { year: 2024, status: "summary", format: "pdf_scanned", isXls: false, hasExpl: true, itemCount: 6 },
  ]],
  ["חיפה", "עיריה", "4000", 6, 285000, 3000000000, "https://www.haifa.muni.il", [
    { year: 2025, status: "missing", format: null, isXls: false, hasExpl: false, itemCount: null },
  ]],
  ["ראשון לציון", "עיריה", "8300", 7, 254384, 2300000000, "https://www.rishonlezion.muni.il", [
    { year: 2025, status: "detailed", format: "pdf_generated", isXls: false, hasExpl: false, itemCount: 210 },
  ]],
  ["פתח תקווה", "עיריה", "7900", 6, 260000, 2400000000, "https://www.pt.gov.il", [
    { year: 2025, status: "summary", format: "pdf_generated", isXls: false, hasExpl: false, itemCount: 5 },
    { year: 2024, status: "missing", format: null, isXls: false, hasExpl: false, itemCount: null },
  ]],
  ["אשדוד", "עיריה", "70", 4, 225939, 2000000000, "https://www.ashdod.muni.il", []],
  ["נתניה", "עיריה", "7400", 5, 230000, 2100000000, "https://www.netanya.muni.il", [
    { year: 2025, status: "detailed", format: "xlsx", isXls: true, hasExpl: true, itemCount: 260 },
    { year: 2024, status: "detailed", format: "xlsx", isXls: true, hasExpl: true, itemCount: 250 },
    { year: 2023, status: "summary", format: "pdf_generated", isXls: false, hasExpl: false, itemCount: 6 },
  ]],
  ["באר שבע", "עיריה", "9000", 4, 213000, 1900000000, "https://www.beer-sheva.muni.il", [
    { year: 2025, status: "summary", format: "xlsx", isXls: true, hasExpl: false, itemCount: 6 },
  ]],
  ["רמת גן", "עיריה", "8600", 7, 163000, 1500000000, "https://www.ramat-gan.muni.il", [
    { year: 2025, status: "detailed", format: "pdf_generated", isXls: false, hasExpl: false, itemCount: 180 },
    { year: 2024, status: "detailed", format: "pdf_generated", isXls: false, hasExpl: false, itemCount: 175 },
    { year: 2023, status: "detailed", format: "pdf_generated", isXls: false, hasExpl: false, itemCount: 170 },
    { year: 2022, status: "detailed", format: "pdf_generated", isXls: false, hasExpl: false, itemCount: 165 },
  ]],
  ["בת ים", "עיריה", "6200", 4, 130000, 1000000000, "https://www.bat-yam.muni.il", [
    { year: 2025, status: "missing", format: null, isXls: false, hasExpl: false, itemCount: null },
    { year: 2024, status: "missing", format: null, isXls: false, hasExpl: false, itemCount: null },
  ]],
  ["הרצליה", "עיריה", "6400", 8, 105000, 1300000000, "https://www.herzliya.muni.il", [
    { year: 2025, status: "detailed", format: "xlsx", isXls: true, hasExpl: true, itemCount: 200 },
  ]],
  ["כפר סבא", "עיריה", "6900", 8, 100000, 900000000, "https://www.kfar-saba.muni.il", [
    { year: 2025, status: "summary", format: "pdf_generated", isXls: false, hasExpl: false, itemCount: 6 },
    { year: 2024, status: "summary", format: "pdf_generated", isXls: false, hasExpl: false, itemCount: 6 },
  ]],
  ["רעננה", "עיריה", "8700", 9, 90000, 850000000, "https://www.raanana.muni.il", [
    { year: 2025, status: "detailed", format: "xlsx", isXls: true, hasExpl: false, itemCount: 190 },
    { year: 2024, status: "summary", format: "pdf_generated", isXls: false, hasExpl: false, itemCount: 6 },
  ]],
  ["מודיעין-מכבים-רעות", "עיריה", "1200", 8, 105000, 950000000, "https://www.modiin.muni.il", []],
  ["אבן יהודה", "מועצה מקומית", "182", 7, 14000, 120000000, "https://www.even-yehuda.muni.il", [
    { year: 2025, status: "detailed", format: "pdf_generated", isXls: false, hasExpl: true, itemCount: 20 },
  ]],
  ["תל מונד", "מועצה מקומית", "154", 8, 16000, 150000000, "https://www.tel-mond.muni.il", [
    { year: 2025, status: "detailed", format: "pdf_generated", isXls: false, hasExpl: false, itemCount: 90 },
    { year: 2024, status: "summary", format: "pdf_generated", isXls: false, hasExpl: false, itemCount: 6 },
  ]],
  ["עומר", "מועצה מקומית", "666", 9, 9000, 90000000, "https://www.omer.muni.il", [
    { year: 2025, status: "detailed", format: "xlsx", isXls: true, hasExpl: false, itemCount: 80 },
  ]],
  ["זכרון יעקב", "מועצה מקומית", "9300", 6, 23000, 220000000, "https://www.zichron.muni.il", [
    { year: 2025, status: "summary", format: "pdf_generated", isXls: false, hasExpl: false, itemCount: 6 },
  ]],
  ["כוכב יאיר-צור יגאל", "מועצה מקומית", "1224", 8, 8000, 75000000, "https://www.kochav-yair.muni.il", []],
  ["קדימה-צורן", "מועצה מקומית", "195", 7, 25000, 230000000, "https://www.kzoran.muni.il", [
    { year: 2025, status: "summary", format: "xlsx", isXls: true, hasExpl: true, itemCount: 6 },
  ]],
  ["מטה יהודה", "מועצה אזורית", "5526", 6, 55000, 552317000, "https://www.m-yehuda.org.il", [
    { year: 2024, status: "detailed", format: "pdf_scanned", isXls: false, hasExpl: false, itemCount: 4 },
  ]],
  ["גזר", "מועצה אזורית", "5530", 5, 45000, 320000000, "https://www.gezer.org.il", [
    { year: 2025, status: "summary", format: "pdf_scanned", isXls: false, hasExpl: false, itemCount: 6 },
    { year: 2024, status: "detailed", format: "pdf_generated", isXls: false, hasExpl: false, itemCount: 60 },
  ]],
  ["חבל מודיעין", "מועצה אזורית", "5525", 6, 20000, 180000000, "https://www.hevel-modiin.org.il", [
    { year: 2025, status: "missing", format: null, isXls: false, hasExpl: false, itemCount: null },
  ]],
  ["מגידו", "מועצה אזורית", "5513", 5, 15000, 140000000, "https://www.megido.org.il", []],
  ["אשכול", "מועצה אזורית", "5538", 4, 14000, 130000000, "https://www.eshkol.org.il", [
    { year: 2025, status: "detailed", format: "xlsx", isXls: true, hasExpl: true, itemCount: 70 },
  ]],
  ["גולן", "מועצה אזורית", "5571", 6, 22000, 200000000, "https://www.golan.org.il", [
    { year: 2025, status: "detailed", format: "pdf_generated", isXls: false, hasExpl: false, itemCount: 55 },
    { year: 2024, status: "summary", format: "pdf_generated", isXls: false, hasExpl: false, itemCount: 6 },
  ]],
];

const municipalities = ROSTER.map(([name, type, muni_id, cluster, population, latest_budget_ils, website_url, checked]) => {
  const years = buildYears(checked);
  const { score, checkedYearsCount } = computeScore(checked);
  return {
    muni_id,
    name,
    type,
    population,
    cluster,
    latest_budget_ils,
    website_url,
    has_pipeline_data: checkedYearsCount > 0,
    years,
    latest_format: latestFormat(checked),
    checked_years_count: checkedYearsCount,
    transparency_score: score,
  };
});

fs.writeFileSync(path.join(OUT_DIR, "municipalities.json"), JSON.stringify(municipalities, null, 2), "utf8");
console.log("municipalities.json:", municipalities.length, "entries");
for (const m of municipalities) console.log(" ", m.name, m.muni_id, "score=", m.transparency_score, "checked=", m.checked_years_count);

// ---- categories.json ----
const CATEGORIES = [
  { code: "81", label: "חינוך", level: 2, parent: "8" },
  { code: "84", label: "רווחה", level: 2, parent: "8" },
  { code: "61", label: "מינהל כללי", level: 2, parent: "6" },
  { code: "71", label: "תברואה", level: 2, parent: "7" },
  { code: "73", label: "תכנון ובנין עיר", level: 2, parent: "7" },
  { code: "87", label: "איכות הסביבה", level: 2, parent: "8" },
  { code: "91", label: "מים", level: 2, parent: "9" },
];

// municipalities with at least one summary/detailed (i.e. "data") checked year
const dataMunis = municipalities.filter((m) =>
  m.years.some((y) => y.status === "summary" || y.status === "detailed")
);
console.log("data municipalities (have at least one summary/detailed year):", dataMunis.length);

// Assign decreasing subsets of dataMunis to each category, sized per the plan's coverage table.
const counts = { "81": 19, "84": 15, "61": 13, "71": 11, "73": 8, "87": 6, "91": 4 };
const assignment = {}; // code -> [muni_id]
const mateYehuda = municipalities.find((m) => m.name === "מטה יהודה");
const FORCE_INCLUDE = { "61": [mateYehuda.muni_id], "84": [mateYehuda.muni_id] }; // real MoI figures exist for these
for (const cat of CATEGORIES) {
  const n = Math.min(counts[cat.code], dataMunis.length);
  const base = dataMunis.slice(0, n).map((m) => m.muni_id);
  const forced = FORCE_INCLUDE[cat.code] || [];
  const merged = [...new Set([...forced, ...base])];
  assignment[cat.code] = merged;
}

const categories = CATEGORIES.map((c) => ({ ...c, municipality_count: assignment[c.code].length }));
fs.writeFileSync(path.join(OUT_DIR, "categories.json"), JSON.stringify(categories, null, 2), "utf8");
console.log("categories.json:", categories.map((c) => `${c.label}:${c.municipality_count}`).join(", "));

// ---- category_values.json + authority_all.json ----
const PCT_RANGE = {
  "81": [0.18, 0.26],
  "84": [0.08, 0.14],
  "61": [0.06, 0.10],
  "71": [0.05, 0.09],
  "73": [0.02, 0.05],
  "87": [0.015, 0.035],
  "91": [0.02, 0.06],
};

// deterministic pseudo-random in [0,1) from a string seed, so re-runs are stable
function seeded(str) {
  let h = 0;
  for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) >>> 0;
  return (h % 1000) / 1000;
}

function pctFor(code, muniId, year) {
  const [lo, hi] = PCT_RANGE[code];
  const r = seeded(`${code}|${muniId}|${year}`);
  return lo + r * (hi - lo);
}

// Real MoI expenditure figures for מטה יהודה 2024, from out/mate_yehuda_2024.json (grand total 552,317,000)
const MATE_YEHUDA_REAL = { "61": 202632000, "81": 250140000, "84": 57798000 };

const categoryValues = {}; // code -> {label, by_municipality: {muni_id: {year: {...}}}}
for (const cat of CATEGORIES) categoryValues[cat.code] = { label: cat.label, by_municipality: {} };

const muniById = Object.fromEntries(municipalities.map((m) => [m.muni_id, m]));

for (const cat of CATEGORIES) {
  for (const muniId of assignment[cat.code]) {
    const m = muniById[muniId];
    const checkedDataYears = m.years.filter((y) => y.status === "summary" || y.status === "detailed");
    const byYear = {};
    for (const y of checkedDataYears) {
      let total_ils;
      if (m.name === "מטה יהודה" && MATE_YEHUDA_REAL[cat.code] !== undefined) {
        total_ils = MATE_YEHUDA_REAL[cat.code];
      } else {
        const pct = pctFor(cat.code, muniId, y.year);
        total_ils = Math.round(pct * m.latest_budget_ils);
      }
      const pct_of_budget = Math.round((total_ils / m.latest_budget_ils) * 1000) / 1000;
      const per_capita = Math.round(total_ils / m.population);
      byYear[y.year] = { total_ils, pct_of_budget, per_capita };
    }
    categoryValues[cat.code].by_municipality[muniId] = byYear;
  }
}

fs.writeFileSync(path.join(OUT_DIR, "category_values.json"), JSON.stringify({ categories: categoryValues }, null, 2), "utf8");
console.log("category_values.json written");

// ---- authority_all.json ----
// level-3 children lookup from the real codebook, for treemap sub-splits
const codebook = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "pipeline", "analysis", "moi_budget_codes.json"), "utf8"));
function level3ChildrenOf(code) {
  return codebook.filter((e) => e.level === 3 && e.parent === code).slice(0, 2);
}

function buildTreemap(muni, categoriesForMuni) {
  const rootLabel = `תקציב ${muni.name}`;
  const labels = [rootLabel];
  const parents = [""];
  const values_total = [null];
  const values_pct_of_budget = [null];
  const values_per_capita = [null];

  for (const code of categoriesForMuni) {
    const cat = CATEGORIES.find((c) => c.code === code);
    const vals = categoryValues[code].by_municipality[muni.muni_id];
    const latestYear = Object.keys(vals).sort((a, b) => b - a)[0];
    if (!latestYear) continue;
    const v = vals[latestYear];
    labels.push(cat.label);
    parents.push(rootLabel);
    values_total.push(v.total_ils);
    values_pct_of_budget.push(v.pct_of_budget);
    values_per_capita.push(v.per_capita);

    const children = level3ChildrenOf(code);
    if (children.length) {
      const splits = [0.6, 0.4];
      children.forEach((child, i) => {
        const share = splits[i] ?? (1 / children.length);
        labels.push(child.label);
        parents.push(cat.label);
        values_total.push(Math.round(v.total_ils * share));
        values_pct_of_budget.push(Math.round(v.pct_of_budget * share * 1000) / 1000);
        values_per_capita.push(Math.round(v.per_capita * share));
      });
    }
  }
  return { labels, parents, values_total, values_pct_of_budget, values_per_capita };
}

function buildPie(muni, categoriesForMuni) {
  const latestYearOverall = Math.max(
    ...categoriesForMuni.flatMap((code) => Object.keys(categoryValues[code].by_municipality[muni.muni_id] || {}).map(Number))
  );
  const slices = [];
  for (const code of categoriesForMuni) {
    const vals = categoryValues[code].by_municipality[muni.muni_id];
    const v = vals[latestYearOverall];
    if (!v) continue;
    const cat = CATEGORIES.find((c) => c.code === code);
    slices.push({ code, label: cat.label, total_ils: v.total_ils, pct: v.pct_of_budget });
  }
  return { year: latestYearOverall, slices };
}

function buildTrend(muni, categoriesForMuni) {
  const years = YEARS.slice().sort((a, b) => a - b);
  const series = categoriesForMuni.map((code) => {
    const cat = CATEGORIES.find((c) => c.code === code);
    const vals = categoryValues[code].by_municipality[muni.muni_id] || {};
    return {
      code,
      label: cat.label,
      total_ils: years.map((y) => (vals[y] ? vals[y].total_ils : null)),
      pct_of_budget: years.map((y) => (vals[y] ? vals[y].pct_of_budget : null)),
      per_capita: years.map((y) => (vals[y] ? vals[y].per_capita : null)),
    };
  });
  return { years, series };
}

function buildSourceFiles(muni) {
  return muni.years
    .filter((y) => y.status !== "not_checked")
    .map((y) => ({ year: y.year, status: y.status, url: y.source_url }));
}

const authorityAll = {};
for (const m of municipalities) {
  const categoriesForMuni = CATEGORIES.filter((c) => assignment[c.code].includes(m.muni_id)).map((c) => c.code);
  if (!m.has_pipeline_data || categoriesForMuni.length === 0) {
    authorityAll[m.muni_id] = {
      muni_id: m.muni_id,
      name: m.name,
      has_pipeline_data: false,
      website_url: m.website_url,
      treemap: { labels: [], parents: [], values_total: [], values_pct_of_budget: [], values_per_capita: [] },
      pie_latest_year: { year: null, slices: [] },
      trend: { years: [], series: [] },
      source_files: buildSourceFiles(m),
    };
    continue;
  }
  authorityAll[m.muni_id] = {
    muni_id: m.muni_id,
    name: m.name,
    has_pipeline_data: true,
    website_url: m.website_url,
    treemap: buildTreemap(m, categoriesForMuni),
    pie_latest_year: buildPie(m, categoriesForMuni),
    trend: buildTrend(m, categoriesForMuni),
    source_files: buildSourceFiles(m),
  };
}

fs.writeFileSync(path.join(OUT_DIR, "authority_all.json"), JSON.stringify(authorityAll, null, 2), "utf8");
console.log("authority_all.json:", Object.keys(authorityAll).length, "entries,",
  Object.values(authorityAll).filter((a) => a.has_pipeline_data).length, "with real bundles");
