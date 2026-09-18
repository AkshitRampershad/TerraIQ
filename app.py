import json

import plotly.graph_objects as go
import requests
import streamlit as st

from engine.catalog import (
    AmbiguousDistrict,
    DistrictNotOnFile,
    available_codes,
    load_bundle,
)
from engine.envelope import compute_envelope
from engine.parcel import Parcel
from engine.program import ProgramAssumptions, compute_program
from engine.report import render_report
from engine.validate import validate_concept
from gpt_functions import generate_building_options
from layout_utils import plot_site
from zoning import (
    district_from_attributes,
    get_zoning_info,
    ordinance_from_attributes,
)

st.set_page_config(page_title="TerraIQ - Parcel Analyzer", layout="wide")
st.title("TerraIQ | Loudoun County Parcel Analyzer")
st.caption(
    "The zoning envelope is computed by a deterministic rule engine with a "
    "citation on every number. The language model only allocates space inside "
    "that envelope, and everything it proposes is checked against it."
)

JURISDICTION = "Loudoun County, VA"

# Streamlit reruns this whole script on every widget interaction anywhere
# on the page - not just ones related to geocoding/zoning/concepts. Without
# caching, adjusting an unrelated input (e.g. the acres spinner) would
# re-fire a live Nominatim/zoning/Groq call every time, quickly tripping
# Nominatim's strict 1 req/sec rate limit and burning Groq API quota for
# no reason. Caching by input keeps each external call to once per unique
# address/coordinate/zoning combination.


@st.cache_data(ttl=1800, show_spinner="Geocoding address...")
def geocode_address(address: str):
    response = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": f"{address}, Loudoun County, VA", "format": "json", "limit": 1},
        # Nominatim's usage policy requires a descriptive User-Agent;
        # requests without one are frequently rejected with a non-JSON
        # response, which crashes a bare .json() call.
        headers={
            "User-Agent": "TerraIQ/1.0 (https://github.com/AkshitRampershad/TerraIQ)"
        },
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=1800, show_spinner="Looking up zoning...")
def cached_zoning_info(lat: float, lon: float):
    return get_zoning_info(lat, lon)


@st.cache_data(ttl=1800, show_spinner="Generating concept plans...")
def cached_concepts(brief_key: str, _envelope, _program, notes: str):
    # brief_key carries the cache identity; the geometry objects are passed
    # with a leading underscore so Streamlit does not try to hash them.
    return generate_building_options(_envelope, _program, notes)


# -- 1. Locate the parcel ------------------------------------------------
st.subheader("1. Locate your parcel")
col1, col2 = st.columns([2, 1])

with col1:
    use_coords = st.checkbox("Enter coordinates instead of an address")
    address_input = "" if use_coords else st.text_input(
        "Parcel address in Loudoun County"
    )
with col2:
    parcel_size_acres = st.number_input("Parcel size (acres)", min_value=0.01, value=0.25)
    frontage_ft = st.number_input(
        "Street frontage (ft, 0 = estimate)", min_value=0.0, value=0.0, step=5.0
    )

coords = None
if use_coords:
    lat = st.number_input("Latitude", value=39.0851, format="%.6f")
    lon = st.number_input("Longitude", value=-77.6454, format="%.6f")
    coords = (lat, lon)
elif address_input:
    try:
        matches = geocode_address(address_input)
    except requests.RequestException as e:
        st.error(f"Geocoding request failed: {e}")
        matches = None
    except ValueError:
        st.error("Geocoding service returned an unexpected (non-JSON) response.")
        matches = None

    if matches:
        coords = (float(matches[0]["lat"]), float(matches[0]["lon"]))
        st.success(f"Found location: {coords[0]:.6f}, {coords[1]:.6f}")
    elif matches is not None:
        st.error("Could not find that address.")

if not coords:
    st.stop()

# -- 2. Zoning lookup ----------------------------------------------------
zoning_info = cached_zoning_info(coords[0], coords[1])
st.subheader("2. Zoning")

if "error" in zoning_info:
    st.error(f"Zoning lookup failed: {zoning_info['error']}")
    st.stop()

district_code, district_field = district_from_attributes(zoning_info)
ordinance = ordinance_from_attributes(zoning_info)
if district_code:
    st.write(
        f"**District:** `{district_code}`  (from GIS field `{district_field}`)"
        + (f" &nbsp;·&nbsp; **Ordinance:** `{ordinance}`" if ordinance else "")
    )
else:
    st.warning(
        "The zoning layer returned attributes but none of the expected district "
        f"fields. Keys present: {', '.join(sorted(zoning_info))}"
    )
    district_code = st.selectbox(
        "Select the district manually", available_codes(JURISDICTION)
    )

with st.expander("Raw zoning attributes from GIS"):
    st.json(zoning_info)

# -- 3. Deterministic envelope ------------------------------------------
st.subheader("3. Buildable envelope (computed, not generated)")

try:
    bundle = load_bundle(JURISDICTION, district_code, ordinance)
except AmbiguousDistrict as e:
    st.error(str(e))
    chosen = st.selectbox("Which ordinance is this parcel zoned under?", ["2023", "1972"])
    bundle = load_bundle(JURISDICTION, district_code, chosen)
except DistrictNotOnFile as e:
    st.error(str(e))
    st.info(
        "The engine deliberately stops here rather than guessing this district's "
        "standards. An invented setback is worse than no answer, because it looks "
        "like one."
    )
    st.stop()

if not bundle.fully_verified:
    st.warning(
        f"The standards on file for {bundle.district} have **not been verified "
        "against the published ordinance**. Everything below demonstrates the "
        "method; it is not a zoning determination. See "
        "`reference/districts/_TEMPLATE.json` for how to transcribe and verify "
        "a district."
    )

with st.sidebar:
    st.header("Modelling assumptions")
    st.caption("These are not zoning standards. They are inputs you can change.")
    floor_to_floor = st.number_input("Floor-to-floor height (ft)", 8.0, 20.0, 10.0, 0.5)
    avg_unit_sf = st.number_input("Average unit size (sf)", 300.0, 4000.0, 950.0, 50.0)
    efficiency = st.slider("Floor plate efficiency", 0.60, 0.95, 0.82, 0.01)
    stall_sf = st.number_input("Surface parking, sf per stall", 250.0, 450.0, 325.0, 5.0)
    notes = st.text_area("Priorities for the concepts (optional)", "")

parcel = Parcel.assumed_rectangle(
    parcel_id=address_input or f"{coords[0]:.5f},{coords[1]:.5f}",
    area_sf=parcel_size_acres * 43_560,
    frontage_ft=frontage_ft or None,
    address=address_input or None,
    jurisdiction=JURISDICTION,
    zoning_district=district_code,
)

st.info(
    "**Lot shape is assumed.** The county GIS query returns zoning for a point, "
    "not the parcel polygon, so the boundary below is a rectangle synthesized "
    "from the acreage you entered. Setback losses depend heavily on real shape "
    "and frontage, so treat the areas as indicative until the parcel geometry is "
    "wired in."
)

envelope = compute_envelope(parcel, bundle, floor_to_floor_ft=floor_to_floor)
program = compute_program(
    envelope,
    ProgramAssumptions(
        avg_unit_sf=avg_unit_sf,
        floor_plate_efficiency=efficiency,
        surface_stall_sf=stall_sf,
        floor_to_floor_ft=floor_to_floor,
    ),
)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Buildable area", f"{envelope.buildable_area_sf:,.0f} sf",
          f"{envelope.buildable_fraction:.0%} of lot")
m2.metric("Max footprint", f"{envelope.max_footprint_sf:,.0f} sf")
m3.metric("Stories", envelope.stories if envelope.stories is not None else "n/a")
m4.metric(
    "Gross floor area",
    f"{program.gross_floor_area_sf:,.0f} sf"
    if program.gross_floor_area_sf is not None
    else "n/a",
)

st.plotly_chart(plot_site(envelope, title="Buildable envelope"), use_container_width=True)

if program.gross_floor_area_sf is not None:
    st.success(f"**Binding constraint: {program.binding_constraint}** — "
               "this is the rule to negotiate, vary, or design around.")

for finding in envelope.blockers + [f for f in program.findings if f.severity == "blocker"]:
    st.error(f"**{finding.title}** — {finding.detail}")

with st.expander("Full analysis, with the authority for every number"):
    st.code(render_report(envelope, program), language="text")

if envelope.blockers:
    st.stop()

# -- 4. Concepts, allocated within the envelope -------------------------
st.subheader("4. Concept plans")
st.caption(
    "Generated by a language model working inside the computed envelope, then "
    "re-checked against it. A concept that exceeds a limit is reported as a "
    "violation rather than drawn."
)

if not st.button("Generate concepts"):
    st.stop()

brief_key = json.dumps(
    {
        "district": bundle.district,
        "footprint": round(envelope.max_footprint_sf),
        "stories": envelope.stories,
        "gfa": round(program.gross_floor_area_sf or 0),
        "units": program.units,
        "notes": notes,
    },
    sort_keys=True,
)
raw = cached_concepts(brief_key, envelope, program, notes)

try:
    payload = json.loads(raw)
except json.JSONDecodeError:
    st.error("The model did not return valid JSON.")
    st.stop()

if "error" in payload:
    st.error(f"Concept generation failed: {payload['error']}")
    st.stop()

options = payload.get("options", [])
if not options:
    st.warning("The model returned no options.")
    st.stop()

for option in options:
    st.markdown(f"### {option.get('option_name', 'Unnamed concept')}")
    if option.get("rationale"):
        st.write(option["rationale"])

    violations = validate_concept(option, envelope, program)
    if violations:
        st.error(
            f"**Rejected — {len(violations)} zoning violation"
            f"{'s' if len(violations) > 1 else ''}.** "
            "This is the check that makes the model safe to use here."
        )
        for v in violations:
            st.markdown(
                f"- **{v.field}**: proposed `{v.proposed}`, limit `{v.limit}` "
                f"— {v.rule}  \n  _{v.citation}_"
            )
    else:
        st.success("Checked against the envelope: compliant.")

    c1, c2, c3 = st.columns(3)
    c1.metric("Gross floor area", f"{option.get('building_area_sft', 0):,} sf")
    c2.metric("Floors", option.get("floors", "-"))
    c3.metric("Units/floor", option.get("units_per_floor", "-"))

    layout = option.get("layout") or {}
    footprint = layout.get("footprint") if isinstance(layout, dict) else None
    st.plotly_chart(
        plot_site(envelope, footprint=footprint, title=option.get("option_name", "Concept")),
        use_container_width=True,
    )

with st.expander("Raw model output"):
    st.json(payload)
