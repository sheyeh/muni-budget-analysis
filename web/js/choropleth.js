// Shared Leaflet choropleth component. Used by Page 1 (page-map.js, colored by transparency
// score) and Page 2 (page-category.js, colored by selected category value).
//
// GeoJSON join note (see web/site-data/geo/JOIN_NOTES.md): feature.properties.CR_PNIM is the
// muni_id join key, but it's zero-padded for codes under 1000 while our muni_id values are not
// — both sides must be normalized (parseInt) before comparing. A single muni_id can also map to
// several disjoint Feature polygons (regional-council exclaves) — style/lookup must key by the
// normalized id, never assume one feature per municipality.
function normalizeMuniId(id) {
  return String(parseInt(id, 10));
}

// Creates a Leaflet choropleth bound to `containerEl`. `getValue(muniId)` must return either
// null/undefined (no data — rendered in the neutral "no boundary/no data" grey) or
// {color, tooltip}. `onFeatureClick(muniId)` fires when a region is clicked.
function createChoropleth(containerEl, geojson, { getValue, onFeatureClick } = {}) {
  const map = L.map(containerEl, { scrollWheelZoom: true }).setView([31.4, 35.0], 7.3);

  // Base map tiles — without these, everything outside our own polygons is blank canvas, making
  // real gaps (areas outside Israeli MoI jurisdiction, e.g. West Bank interior/Gaza; a handful of
  // regional councils missing a "general area" row — see JOIN_NOTES.md) indistinguishable from a
  // rendering bug. Light, label-light basemap so the choropleth colors stay the focus.
  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: "abcd",
    maxZoom: 19,
  }).addTo(map);

  let currentGetValue = getValue || (() => null);

  function styleFor(feature) {
    const muniId = normalizeMuniId(feature.properties.CR_PNIM);
    const v = currentGetValue(muniId);
    return {
      color: "#888",
      weight: 0.5,
      fillColor: v ? v.color : Format.bandColor("grey"),
      // Lighter fill for "no data yet" so it reads as neutral background, not a wall of failure —
      // most of the country is grey today (only a handful of municipalities are mocked/real).
      fillOpacity: v ? 0.85 : 0.35,
    };
  }

  const layer = L.geoJSON(geojson, {
    style: styleFor,
    onEachFeature(feature, lyr) {
      const muniId = normalizeMuniId(feature.properties.CR_PNIM);
      const name = feature.properties.Muni_Heb || "";
      lyr.bindTooltip(() => {
        const v = currentGetValue(muniId);
        const label = v && v.tooltip ? v.tooltip : "אין נתונים עדיין";
        return `<strong>${name}</strong><br/>${label}`;
      });
      lyr.on("click", () => {
        if (onFeatureClick) onFeatureClick(muniId);
      });
    },
  }).addTo(map);

  // Defer size/bounds fitting to the next frame: at this exact synchronous point (right after
  // container.innerHTML was just assigned by the caller) the browser may not have finished a
  // layout pass yet, so containerEl's measured size can be stale/wrong here — Leaflet would then
  // cache a bad internal viewport and/or fitBounds would compute the wrong zoom/center against
  // that bad size, rendering only a small sliver of tiles in an otherwise-blank box. Confirmed via
  // a real repro on Page 2 (flex-column container): the DOM box sized correctly but the map's
  // rendered pane didn't fill it until deferred like this.
  requestAnimationFrame(() => {
    map.invalidateSize();
    try {
      map.fitBounds(layer.getBounds(), { padding: [10, 10] });
    } catch (e) {
      // empty geojson — keep default view
    }
  });

  return {
    map,
    layer,
    // Re-styles every feature using a new getValue(muniId) function (Page 2's toggle/category switch).
    update(newGetValue) {
      currentGetValue = newGetValue || (() => null);
      layer.setStyle(styleFor);
    },
    invalidateSize() {
      map.invalidateSize();
    },
  };
}
