# Loudoun County GIS exports

CSV exports of Loudoun County GIS layers, supplied 2025-08.

## What is here

| File | Rows | Committed |
| --- | --- | --- |
| `Loudoun_Zoning.csv` | 1,260 | in full (494 KB) |
| `Loudoun_HistoricQuarry_Overlay_Zones.csv` | 9 | in full (1 KB) |
| `sample_Loudoun_Parcels.csv` | 499 of 131,851 | sample |
| `sample_Loudoun_Parcel_Coordinates.csv` | 499 of 131,413 | sample |
| `sample_Loudoun_Soils_Overlays.csv` | 199 | sample |

The full parcel, coordinate and soils files are 14 MB, 10 MB and 22 MB. They are
not committed: 46 MB of CSV in git history slows every clone of this repository
forever, and the samples are enough to develop and test the readers against.
Point the ingest at your local copies to run over the whole county.

## The important limitation

**These exports contain no polygon geometry.** `SHAPE_Length` and `SHAPE_Area`
are ArcGIS shape metadata — a perimeter and an area measurement — not
coordinates. The only real coordinates anywhere in the export are parcel
centroids, one point per parcel, in `Loudoun_Parcel_Coordinates_lat_long.csv`
(`POINT_X`/`POINT_Y` in WGS84, `POINT_X_SP`/`POINT_Y_SP` in Virginia State
Plane feet).

What follows from that:

- **No true setback geometry.** Setbacks are measured perpendicular from each
  lot line, so they need the boundary. See `engine/parcel.py` for the
  equivalent-rectangle stand-in these files do support, and its limits.
- **Zoning cannot be joined to parcels here.** `Loudoun_Zoning.csv` carries only
  `OBJECTID`/`NEW_ID` — no parcel key. Assigning a district to a parcel is a
  spatial join, which needs polygons. The live ArcGIS query in `zoning.py`
  remains the way to get a parcel's district.
- **The soils and quarry overlays cannot be applied.** No geometry and no parcel
  key, so they can neither be subtracted from an envelope nor attributed to a
  parcel. They are committed for reference only.

To get polygons, re-export as GeoJSON or shapefile rather than CSV, or query the
ArcGIS REST endpoint with `returnGeometry=true`.

## What the zoning layer does give

54 distinct districts with official names, descriptions, and the ordinance they
fall under — 1,173 rows under the 2023 ordinance and 87 still under the 1972
ordinance. **No dimensional standards**: across all 54 district descriptions
there is not one mention of a setback, yard, height, floor area ratio or lot
coverage. Eight districts state a density in prose, and those are transcribable;
see `tools/build_district_catalog.py`.
