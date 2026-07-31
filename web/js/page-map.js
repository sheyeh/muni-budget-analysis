// Page 1 — מפת השקיפות (Transparency Map, home). Choropleth colored by transparency_score band
// + a sortable AND filterable table (every column). Clicking a map region or a table row's name
// navigates to Page 3.
const PageMap = (() => {
  let initialized = false;
  let municipalities = [];
  let choropleth = null;
  let sortCol = "transparency_score";
  let sortDir = "desc";

  const YEAR_COLS = [2026, 2025, 2024, 2023, 2022];
  const STATUS_OPTIONS = ["not_checked", "missing", "summary", "detailed"];
  const BAND_OPTIONS = ["green", "orange", "red", "grey"];
  const BAND_LABELS = { green: "ירוק (≥70)", orange: "כתום (40–69)", red: "אדום (<40)", grey: "אין נתונים" };

  // filters: name (substring), type/cluster/format (exact-match dropdown, "" = all),
  // population/budget (numeric minimum), year:<y> (status dropdown), score (band dropdown)
  const filters = {
    name: "",
    type: "",
    populationMin: "",
    budgetMin: "",
    cluster: "",
    format: "",
    score: "",
  };
  for (const y of YEAR_COLS) filters[`year:${y}`] = "";

  function goToAuthority(muniId) {
    window.location.hash = `#/authority?muni_id=${encodeURIComponent(muniId)}`;
  }

  function yearRank(yearEntry) {
    if (!yearEntry) return -1;
    return { not_checked: -1, missing: 0, summary: 1, detailed: 2 }[yearEntry.status];
  }

  function yearOf(muni, year) {
    return muni.years.find((y) => y.year === year);
  }

  function sortValue(muni, col) {
    if (col === "name" || col === "type") return muni[col];
    if (col === "population" || col === "latest_budget_ils" || col === "cluster" || col === "transparency_score") {
      return muni[col] === null || muni[col] === undefined ? -Infinity : muni[col];
    }
    if (col.startsWith("year:")) {
      const y = parseInt(col.split(":")[1], 10);
      return yearRank(yearOf(muni, y));
    }
    return 0;
  }

  function passesFilters(m) {
    if (filters.name.trim() && !m.name.includes(filters.name.trim())) return false;
    if (filters.type && m.type !== filters.type) return false;
    if (filters.cluster && String(m.cluster) !== filters.cluster) return false;
    if (filters.format && m.latest_format !== filters.format) return false;
    if (filters.populationMin && !(m.population >= Number(filters.populationMin))) return false;
    if (filters.budgetMin && !(m.latest_budget_ils >= Number(filters.budgetMin))) return false;
    if (filters.score && Format.scoreBand(m.transparency_score) !== filters.score) return false;
    for (const y of YEAR_COLS) {
      const want = filters[`year:${y}`];
      if (want) {
        const ye = yearOf(m, y);
        if (!ye || ye.status !== want) return false;
      }
    }
    return true;
  }

  function applySortFilter() {
    let rows = municipalities.filter(passesFilters);
    rows = [...rows].sort((a, b) => {
      const av = sortValue(a, sortCol);
      const bv = sortValue(b, sortCol);
      let cmp;
      if (typeof av === "string") cmp = av.localeCompare(bv, "he");
      else cmp = av - bv;
      return sortDir === "asc" ? cmp : -cmp;
    });
    return rows;
  }

  function renderTableBody(tbody) {
    const rows = applySortFilter();
    tbody.innerHTML = "";
    for (const m of rows) {
      const tr = document.createElement("tr");
      const band = Format.scoreBand(m.transparency_score);

      const cells = [];
      cells.push(`<td><a href="#/authority?muni_id=${encodeURIComponent(m.muni_id)}" class="muni-link">${m.name}</a></td>`);
      cells.push(
        `<td class="score-cell score-${band}">${m.transparency_score === null ? "—" : m.transparency_score}</td>`
      );
      cells.push(`<td>${m.type}</td>`);
      cells.push(`<td>${Format.number(m.population)}</td>`);
      cells.push(`<td>${Format.ils(m.latest_budget_ils)}</td>`);
      cells.push(`<td>${m.cluster ?? "—"}</td>`);
      cells.push(`<td>${Format.formatLabel(m.latest_format)}</td>`);
      for (const y of YEAR_COLS) {
        const ye = yearOf(m, y);
        const badge = Format.yearBadge(ye);
        const hasLink = ye && ye.source_url;
        cells.push(
          hasLink
            ? `<td><a class="badge ${badge.cssClass}" href="${ye.source_url}" target="_blank" rel="noopener">${badge.text}</a></td>`
            : `<td><span class="badge ${badge.cssClass}">${badge.text}</span></td>`
        );
      }
      tr.innerHTML = cells.join("");
      tbody.appendChild(tr);
    }
    const countEl = document.getElementById("map-table-count");
    if (countEl) countEl.textContent = `${rows.length} מתוך ${municipalities.length} רשויות`;
  }

  function wireSortHeaders(theadRow, tbody) {
    theadRow.querySelectorAll("th[data-col]").forEach((th) => {
      th.addEventListener("click", () => {
        const col = th.dataset.col;
        if (sortCol === col) {
          sortDir = sortDir === "asc" ? "desc" : "asc";
        } else {
          sortCol = col;
          sortDir = "desc";
        }
        renderTableBody(tbody);
      });
    });
  }

  function optionsHtml(values, labelFor) {
    return values.map((v) => `<option value="${v}">${labelFor ? labelFor(v) : v}</option>`).join("");
  }

  function buildFilterRow() {
    const types = [...new Set(municipalities.map((m) => m.type))];
    const clusters = [...new Set(municipalities.map((m) => m.cluster).filter((c) => c !== null))].sort((a, b) => a - b);
    const formats = [...new Set(municipalities.map((m) => m.latest_format).filter(Boolean))];
    const statusLabelFor = (s) => Format.STATUS_LABELS[s];

    const yearSelects = YEAR_COLS.map(
      (y) => `<th><select data-filter="year:${y}"><option value="">הכל</option>${optionsHtml(STATUS_OPTIONS, statusLabelFor)}</select></th>`
    ).join("");

    return `
      <tr class="filter-row">
        <th><input type="text" data-filter="name" placeholder="חיפוש שם..." /></th>
        <th><select data-filter="score"><option value="">הכל</option>${optionsHtml(BAND_OPTIONS, (b) => BAND_LABELS[b])}</select></th>
        <th><select data-filter="type"><option value="">הכל</option>${optionsHtml(types)}</select></th>
        <th><input type="number" data-filter="populationMin" placeholder="מינימום" /></th>
        <th><input type="number" data-filter="budgetMin" placeholder="מינימום" /></th>
        <th><select data-filter="cluster"><option value="">הכל</option>${optionsHtml(clusters)}</select></th>
        <th><select data-filter="format"><option value="">הכל</option>${optionsHtml(formats, (f) => Format.formatLabel(f))}</select></th>
        ${yearSelects}
      </tr>
    `;
  }

  function wireFilterRow(filterRow, tbody) {
    filterRow.querySelectorAll("[data-filter]").forEach((el) => {
      const key = el.dataset.filter;
      const evt = el.tagName === "SELECT" ? "change" : "input";
      el.addEventListener(evt, () => {
        filters[key] = el.value;
        renderTableBody(tbody);
      });
    });
  }

  function getValueForChoropleth(muniId) {
    const m = municipalities.find((x) => String(parseInt(x.muni_id, 10)) === muniId);
    if (!m) return null;
    const band = Format.scoreBand(m.transparency_score);
    const scoreText = m.transparency_score === null ? "אין נתונים עדיין" : `ציון שקיפות: ${m.transparency_score}`;
    return { color: Format.bandColor(band), tooltip: scoreText };
  }

  async function render(container) {
    const [munisData, geo] = await Promise.all([Data.getMunicipalities(), Data.getGeoJSON()]);
    municipalities = munisData;

    container.innerHTML = `
      <div class="page-map">
        <div class="table-panel">
          <div class="table-controls">
            <span id="map-table-count" class="table-count"></span>
            <div class="legend-wrap">
              <button type="button" class="legend-hint" id="score-legend-toggle">מקרא - איך מחושב הציון</button>
              <div class="legend-popover hidden" id="score-legend-popover">
                <p><strong>ציון שקיפות תקציבית</strong> — מחושב לכל רשות על פני 5 השנים האחרונות שנבדקו בפועל.</p>
                <p>לכל שנה שנבדקה: <strong>0</strong> נק' אם אין מידע, <strong>7</strong> נק' אם פורסמה תמצית תקציב בלבד, <strong>15</strong> נק' אם פורסם תקציב מפורט.</p>
                <p>בונוסים לשנה שנבדקה: <strong>+3</strong> אם הקובץ בפורמט XLS, <strong>+2</strong> אם כולל הסבר מילולי (מקסימום 20 נק' לשנה).</p>
                <p>הציון הסופי מנורמל ל-100 לפי מספר השנים שנבדקו בפועל, כך שרשות שנבדקה רק בחלק מהשנים עדיין יכולה להגיע לציון מלא.</p>
                <p>רשות שטרם נבדקה כלל (0 שנים) מוצגת באפור — "אין נתונים עדיין", לא ציון נמוך.</p>
              </div>
            </div>
          </div>
          <div class="table-scroll">
            <table class="muni-table">
              <thead>
                <tr>
                  <th data-col="name">שם הרשות ▾</th>
                  <th data-col="transparency_score">ציון שקיפות תקציבית ▾</th>
                  <th data-col="type">סוג ▾</th>
                  <th data-col="population">מספר תושבים ▾</th>
                  <th data-col="latest_budget_ils">גובה תקציב ▾</th>
                  <th data-col="cluster">אשכול למס ▾</th>
                  <th>פורמט פרסום</th>
                  ${YEAR_COLS.map((y) => `<th data-col="year:${y}">${y} ▾</th>`).join("")}
                </tr>
                ${buildFilterRow()}
              </thead>
              <tbody id="map-table-body"></tbody>
            </table>
          </div>
        </div>
        <div id="map-canvas" class="map-canvas"></div>
      </div>
    `;

    const mapCanvas = container.querySelector("#map-canvas");
    choropleth = createChoropleth(mapCanvas, geo, {
      getValue: getValueForChoropleth,
      onFeatureClick: goToAuthority,
    });

    const legendToggle = container.querySelector("#score-legend-toggle");
    const legendPopover = container.querySelector("#score-legend-popover");
    legendToggle.addEventListener("click", (e) => {
      e.stopPropagation();
      legendPopover.classList.toggle("hidden");
    });
    document.addEventListener("click", (e) => {
      if (!legendPopover.contains(e.target) && e.target !== legendToggle) {
        legendPopover.classList.add("hidden");
      }
    });

    const tbody = container.querySelector("#map-table-body");
    const theadRows = container.querySelectorAll("thead tr");
    wireSortHeaders(theadRows[0], tbody);
    wireFilterRow(theadRows[1], tbody);
    renderTableBody(tbody);
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
