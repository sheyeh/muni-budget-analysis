// Page 2 — לפי סעיף (By Category). Single-select category drives the map color + trend chart;
// a multi-select authority checklist controls which municipalities appear as trend lines.
// 3-way display-mode toggle (total / % of budget / per-capita) affects both the map and the chart.
const PageCategory = (() => {
  let initialized = false;
  let municipalities = [];
  let categories = [];
  let categoryValues = {}; // code -> {label, by_municipality}
  let choropleth = null;

  let selectedCategory = null; // code
  let selectedMunicipalities = new Set(); // muni_id
  let mode = "total_ils"; // total_ils | pct_of_budget | per_capita

  const MODE_LABELS = {
    total_ils: "סכום כולל",
    pct_of_budget: "באחוזים מתקציב הרשות",
    per_capita: "בשקלים לתושב",
  };

  function muniName(muniId) {
    const m = municipalities.find((x) => x.muni_id === muniId);
    return m ? m.name : muniId;
  }

  function formatValue(v) {
    if (v === null || v === undefined) return "—";
    if (mode === "total_ils") return Format.ils(v);
    if (mode === "pct_of_budget") return Format.pct(v);
    return Format.perCapita(v);
  }

  function latestYearFor(muniId) {
    const byMuni = categoryValues[selectedCategory].by_municipality[muniId];
    if (!byMuni) return null;
    const years = Object.keys(byMuni).map(Number);
    return years.length ? Math.max(...years) : null;
  }

  function valueFor(muniId, year) {
    const byMuni = categoryValues[selectedCategory].by_municipality[muniId];
    if (!byMuni || !byMuni[year]) return null;
    return byMuni[year][mode];
  }

  function municipalitiesWithData() {
    const cat = categoryValues[selectedCategory];
    if (!cat) return [];
    return Object.keys(cat.by_municipality);
  }

  function getValueForChoropleth() {
    const muniIds = municipalitiesWithData();
    const latestValues = muniIds
      .map((id) => ({ id, v: valueFor(id, latestYearFor(id)) }))
      .filter((x) => x.v !== null);
    const min = latestValues.length ? Math.min(...latestValues.map((x) => x.v)) : 0;
    const max = latestValues.length ? Math.max(...latestValues.map((x) => x.v)) : 0;
    const catLabel = categoryValues[selectedCategory].label;

    return (normalizedMuniId) => {
      const m = municipalities.find((x) => String(parseInt(x.muni_id, 10)) === normalizedMuniId);
      if (!m) return null;
      const v = valueFor(m.muni_id, latestYearFor(m.muni_id));
      if (v === null) return null;
      return {
        color: Format.valueColor(v, min, max),
        tooltip: `${catLabel}: ${formatValue(v)}`,
      };
    };
  }

  function renderChart() {
    const years = [...new Set(Object.values(categoryValues[selectedCategory].by_municipality).flatMap((y) => Object.keys(y).map(Number)))].sort(
      (a, b) => a - b
    );
    const traces = [...selectedMunicipalities].map((muniId) => {
      const byMuni = categoryValues[selectedCategory].by_municipality[muniId] || {};
      return {
        type: "scatter",
        mode: "lines+markers",
        name: muniName(muniId),
        x: years,
        y: years.map((y) => (byMuni[y] ? byMuni[y][mode] : null)),
        connectgaps: false,
      };
    });
    const el = document.getElementById("category-chart");
    if (!traces.length) {
      Plotly.purge(el);
      el.innerHTML = '<div class="page-placeholder">בחרו רשויות להשוואה מהרשימה מימין</div>';
      return;
    }
    el.innerHTML = "";
    Plotly.newPlot(
      el,
      traces,
      {
        title: `${categoryValues[selectedCategory].label} — ${MODE_LABELS[mode]}`,
        margin: { t: 40, r: 20, l: 50, b: 40 },
        xaxis: { title: "שנה", dtick: 1 },
        yaxis: { title: MODE_LABELS[mode] },
        legend: { orientation: "h" },
      },
      { responsive: true, displaylogo: false }
    );
  }

  function refreshMapAndChart() {
    choropleth.update(getValueForChoropleth());
    renderChart();
  }

  function renderCategoryList(container, filterText) {
    const q = (filterText || "").trim();
    const list = categories.filter((c) => !q || c.label.includes(q));
    container.innerHTML = list
      .map(
        (c) => `
        <div class="pick-row ${c.code === selectedCategory ? "picked" : ""}" data-code="${c.code}">
          <span>${c.label}</span>
          <span class="pick-count">(${c.municipality_count})</span>
        </div>`
      )
      .join("");
    container.querySelectorAll(".pick-row").forEach((row) => {
      row.addEventListener("click", () => selectCategory(row.dataset.code));
    });
  }

  function defaultMunicipalitiesFor(code) {
    const ids = Object.keys(categoryValues[code].by_municipality);
    return new Set(ids.slice(0, 8));
  }

  function selectCategory(code) {
    selectedCategory = code;
    selectedMunicipalities = defaultMunicipalitiesFor(code);
    renderCategoryList(document.getElementById("category-list"), document.getElementById("category-search").value);
    renderAuthorityChecklist(document.getElementById("authority-checklist"), document.getElementById("authority-search").value);
    refreshMapAndChart();
  }

  function renderAuthorityChecklist(container, filterText) {
    const q = (filterText || "").trim();
    const ids = municipalitiesWithData();
    const filtered = ids.filter((id) => !q || muniName(id).includes(q));
    container.innerHTML = filtered
      .map(
        (id) => `
        <label class="checklist-row">
          <input type="checkbox" data-muni-id="${id}" ${selectedMunicipalities.has(id) ? "checked" : ""} />
          <span>${muniName(id)}</span>
        </label>`
      )
      .join("");
    container.querySelectorAll("input[type=checkbox]").forEach((cb) => {
      cb.addEventListener("change", () => {
        if (cb.checked) selectedMunicipalities.add(cb.dataset.muniId);
        else selectedMunicipalities.delete(cb.dataset.muniId);
        renderChart();
      });
    });
  }

  async function render(container) {
    const [munisData, cats, catVals, geo] = await Promise.all([
      Data.getMunicipalities(),
      Data.getCategories(),
      Data.getCategoryValues(),
      Data.getGeoJSON().catch((err) => {
        console.error(err);
        return null; // chart/list still render; choropleth just shows base map with no polygons
      }),
    ]);
    municipalities = munisData;
    categories = cats;
    categoryValues = catVals.categories;

    container.innerHTML = `
      <div class="page-category">
        <div class="side-panel">
          <div class="side-block">
            <input type="text" id="category-search" placeholder="חיפוש סעיף..." />
            <div id="category-list" class="pick-list"></div>
          </div>
          <div class="side-block">
            <input type="text" id="authority-search" placeholder="חיפוש רשות להשוואה..." />
            <div id="authority-checklist" class="checklist"></div>
          </div>
        </div>
        <div class="category-main">
          <div id="map-canvas-cat" class="map-canvas"></div>
          <div class="mode-toggle" id="mode-toggle">
            ${Object.entries(MODE_LABELS)
              .map(
                ([key, label]) =>
                  `<label><input type="radio" name="mode" value="${key}" ${key === mode ? "checked" : ""}/> ${label}</label>`
              )
              .join("")}
          </div>
          <div id="category-chart" class="chart-canvas"></div>
        </div>
      </div>
    `;

    // Default: category with the highest coverage count.
    const best = [...categories].sort((a, b) => b.municipality_count - a.municipality_count)[0];
    selectedCategory = best.code;
    selectedMunicipalities = defaultMunicipalitiesFor(selectedCategory);

    const mapCanvas = container.querySelector("#map-canvas-cat");
    choropleth = createChoropleth(mapCanvas, geo, {
      getValue: getValueForChoropleth(),
      onFeatureClick: (muniId) => {
        window.location.hash = `#/authority?muni_id=${encodeURIComponent(muniId)}`;
      },
    });

    renderCategoryList(container.querySelector("#category-list"));
    renderAuthorityChecklist(container.querySelector("#authority-checklist"));
    renderChart();

    container.querySelector("#category-search").addEventListener("input", (e) => {
      renderCategoryList(container.querySelector("#category-list"), e.target.value);
    });
    container.querySelector("#authority-search").addEventListener("input", (e) => {
      renderAuthorityChecklist(container.querySelector("#authority-checklist"), e.target.value);
    });
    container.querySelector("#mode-toggle").addEventListener("change", (e) => {
      mode = e.target.value;
      refreshMapAndChart();
    });
  }

  async function show(container) {
    if (!initialized) {
      initialized = true;
      await render(container);
    } else if (choropleth) {
      choropleth.invalidateSize();
    }
    container.classList.remove("hidden");
  }

  function hide(container) {
    container.classList.add("hidden");
  }

  return { show, hide };
})();
