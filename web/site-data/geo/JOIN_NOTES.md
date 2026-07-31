# GeoJSON join notes

Source: Ministry of Interior (משרד הפנים) official layer "גבולות שיפוט רשויות מקומיות וועדים
מקומיים" (Jurisdiction Boundaries of Local Authorities and Local Committees), ArcGIS FeatureServer:
`https://services1.arcgis.com/hWUp5lYOh3Fi9WoQ/arcgis/rest/services/GvulotShputRashuyotVaadim/FeatureServer/0`

The layer has 1,808 raw features nationally (one row per local-committee sub-area, plus one
"general area" row per municipality). `web/site-data/geo/municipalities.geojson` here is a
**filtered** subset (678 features, ~15.6MB) — see filtering rule below — not the raw layer.

## Join key

`feature.properties.CR_PNIM` = the Ministry of Interior semel-yishuv authority code, i.e. the
same identifier this project uses as `muni_id` (see `CONTEXT.md`'s "Muni ID" glossary entry).

**Format mismatch, verified**: `CR_PNIM` is a zero-padded string for codes under 1000 (e.g.
`"0182"` for אבן יהודה) but plain for codes ≥1000 (e.g. `"5000"` for תל אביב-יפו, `"5526"` for
מטה יהודה). This project's `municipalities.json` `muni_id` values are NOT zero-padded. **The
frontend join must normalize both sides** (`parseInt()` or strip leading zeros) before comparing
— a plain string `===` will silently fail for every council with a code under 1000, which is most
local/regional councils (city semel codes tend to be ≥1000).

## Filtering applied (already done, in the vendored file)

The raw layer's `Vaad_Heb` field is `"שטח כללי"` ("general area") for a municipality's own
directly-governed land, a specific local-committee name (e.g. `"אום בטין"`) for each of a
regional council's constituent settlements, or blank (`" "`) for municipalities with no
sub-committees (cities/local councils). **Server-side ArcGIS `where` filtering on the Hebrew
`Vaad_Heb` value was unreliable** (a `where=Vaad_Heb='שטח כללי'` query silently returned only the
blank-value rows and dropped every regional council) — do not rely on ArcGIS `where` for Hebrew
string equality; fetch all rows and filter client-side instead, which is what was done here.

The vendored file keeps only rows where `Vaad_Heb === "שטח כללי"` OR `Vaad_Heb === " "` (blank),
dropping the ~1,130 named-sub-committee rows. Result: 678 features covering **305 unique
`CR_PNIM` values** (out of 309 unique values in the full raw layer — **4 regional councils
have no general-area or blank row at all** in the source data: CR_PNIM `5545`, `5528`, `5565`,
`5566`; these will have no polygon in this file and must render as "no boundary available",
distinct from "not yet assessed" — a real, small data gap, not a bug in the filtering).

## Regional councils are still multi-feature (by design, not a bug)

Even after filtering, a regional council's `CR_PNIM` can map to **more than one Feature** —
confirmed live, e.g. מטה יהודה (`5526`) has 4 separate `"שטח כללי"` features, one per disjoint
patch of land the council directly governs (real, disconnected exclaves). This is correct/expected
geography, not a duplicate-data bug. **Do not `unique()`-key the GeoJSON by `CR_PNIM` expecting one
feature** — a choropleth must style *all* features sharing a `CR_PNIM` the same way (loop/lookup by
id, not by array index), and a single municipality may legitimately paint as several disconnected
polygons on the map.

## Type field spelling

The layer's `Sug_Muni` field spells city authorities `"עירייה"` (two yods). This project's
`municipalities.json` uses `"עיריה"` (one yod) per its own convention. Not a join blocker (`type`
isn't the join key) but normalize/compare loosely if anything ever cross-checks the two. Regional
councils (`"מועצה אזורית"`) and local councils (`"מועצה מקומית"`) match our convention exactly.

## Coverage

`web/site-data/municipalities.json` currently hand-authors only 26 of ~305 real municipalities
present in this GeoJSON. Every polygon with no matching `muni_id` in `municipalities.json` should
render in the grey "not yet assessed" band by default — consistent with a not-yet-processed
municipality, per the parent plan (`lets-plan-a-ui-virtual-wind.md`).

## Verified live (not assumed)

- תל אביב - יפו → `CR_PNIM "5000"` (matches the well-known public semel yishuv)
- אבן יהודה → `CR_PNIM "0182"`
- מטה יהודה → `CR_PNIM "5526"` (4 disjoint polygon parts)

## Blank patches on the map that are NOT bugs

Rendering the map with a real basemap underneath (Phase 1) surfaced visible gaps where no colored
polygon exists at all. Two real, expected causes — confirmed against the raw 1808-feature layer,
not assumed:

1. **Settlements inside a regional council are not independent authorities.** A village like
   עתלית (Atlit) has no `muni_id`/`CR_PNIM` of its own — it's administratively part of חוף הכרמל
   regional council's territory, and only appears in the raw layer as one of that council's named
   sub-committee (`Vaad_Heb`) rows, which this file deliberately excludes (see "Filtering applied"
   above). It will never get its own colored region here; it's absorbed into its regional
   council's polygon. This is correct, not a missing-data bug — the product's `muni_id` concept is
   "independent local authority," not "named place."
2. **Genuine "no jurisdiction" buffer zones exist in real life.** The raw layer has ~90 features
   named `"ללא שיפוט - אזור ..."` ("no jurisdiction — ... area", e.g. `"ללא שיפוט - אזור הר
   הכרמל"`) — real administrative land that belongs to no local authority. These are correctly
   excluded from the vendored file (their `Vaad_Heb` doesn't match the general-area/blank filter),
   so they render as plain basemap with no color overlay — which is the most accurate
   representation available. This matches the original product mockup's own reference map, which
   had a distinct legend entry for exactly this ("area without local authority").

Net effect: the map's blank patches are a mix of (a) real geography outside any Israeli local
authority's jurisdiction (expected, matches the mockup), and (b) the 4 small regional councils
with a genuine data gap in the source layer noted above. Nothing here should be "fixed" by trying
to fill these gaps with synthetic polygons.
