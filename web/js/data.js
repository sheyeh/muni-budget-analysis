// Fetch + in-memory cache, shared across pages so switching tabs doesn't re-fetch.
// DB-only: sourced entirely from the live Supabase project (db-data.js) — static
// site-data/*.json mock files are no longer read by the app.
const Data = (() => {
  const cache = {};

  function loadJSON(key, path) {
    if (!cache[key]) {
      cache[key] = fetch(path).then((res) => {
        if (!res.ok) throw new Error(`Failed to load ${path}: ${res.status}`);
        return res.json();
      });
    }
    return cache[key];
  }

  function loadDb() {
    if (!cache.db) {
      cache.db = DbData.fetchAll();
    }
    return cache.db;
  }

  async function getMunicipalities() {
    const db = await loadDb();
    return db.municipalities;
  }

  async function getCategories() {
    const db = await loadDb();
    // Only "61" (מינהל כללי) has any line-item data in this DB — see db-data.js's module comment.
    const count = Object.keys(db.category61ByMuni).length;
    if (!count) return [];
    return [{ code: "61", label: "מינהל כללי", level: 2, parent: "6", municipality_count: count }];
  }

  async function getCategoryValues() {
    const db = await loadDb();
    return { categories: { "61": { label: "מינהל כללי", by_municipality: db.category61ByMuni } } };
  }

  async function getAuthorityAll() {
    const db = await loadDb();
    return db.authorityAll;
  }

  return {
    getMunicipalities,
    getCategories,
    getCategoryValues,
    getAuthorityAll,
    getGeoJSON: () => loadJSON("geo", "site-data/geo/municipalities.geojson"),
  };
})();
