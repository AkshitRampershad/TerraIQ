"""Concept generation, constrained by a computed envelope.

The model is given the envelope as a hard budget and asked to allocate within
it. It never decides how much may be built -- `engine.envelope` already did,
deterministically and with citations -- and whatever it returns is checked by
`engine.validate` before anything is shown as a plan.

This is the difference between an assistant that proposes designs and one that
invents zoning. Only the first is defensible downstream.
"""

import json

import requests

from groq_client import GROQ_API_URL, GROQ_MODEL, get_groq_api_key


def _envelope_brief(envelope, program):
    """The hard budget the model must work inside, as plain numbers."""
    p = envelope.parcel
    lines = [
        f"Lot area: {p.area_sf:,.0f} sf ({p.area_acres:.3f} acres)",
        f"Zoning district: {envelope.bundle.district} "
        f"({envelope.bundle.district_name}), {envelope.bundle.jurisdiction}",
        f"Buildable area after setbacks and overlays: "
        f"{envelope.buildable_area_sf:,.0f} sf",
        f"Largest contiguous buildable region: {envelope.largest_contiguous_sf:,.0f} sf",
        f"MAXIMUM footprint: {envelope.max_footprint_sf:,.0f} sf",
        f"MAXIMUM stories: {envelope.stories}",
        f"MAXIMUM height: {envelope.height_ft} ft",
    ]
    if program.gross_floor_area_sf is not None:
        lines.append(f"MAXIMUM gross floor area: {program.gross_floor_area_sf:,.0f} sf")
    if program.units is not None:
        lines.append(f"MAXIMUM dwelling units: {program.units}")
    if program.parking_required is not None:
        lines.append(
            f"Parking: {program.parking_required} spaces required at the modelled "
            f"unit count; {program.land_left_for_parking_sf:,.0f} sf of land remains "
            f"after footprint and open space"
        )
    lines.append(f"Binding constraint: {program.binding_constraint}")

    bounds = envelope.buildable.bounds
    if bounds:
        lines.append(
            "Buildable region bounding box, in the parcel's own plane-feet "
            f"coordinates: x {bounds[0]:.1f} to {bounds[2]:.1f}, "
            f"y {bounds[1]:.1f} to {bounds[3]:.1f}"
        )
    return "\n".join(lines)


def generate_building_options(envelope, program, notes=""):
    """Ask the model to allocate the envelope into 2-3 concepts.

    Returns the raw JSON string from the model. Validation happens in
    `engine.validate.validate_concept`, not here -- generation and checking
    stay separate so the check cannot be talked out of by the thing it checks.
    """
    api_key = get_groq_api_key()
    if not api_key:
        return json.dumps(
            {"error": "GROQ_API_KEY is not configured. Add it in Streamlit secrets."}
        )

    prompt = f"""A zoning rule engine has already computed what this parcel allows.
Those numbers are fixed and were derived from the ordinance. Do not recompute
them, do not exceed them, and do not cite zoning rules of your own.

{_envelope_brief(envelope, program)}

{("Owner's priorities: " + notes) if notes else ""}

Propose 2-3 distinct concepts that use this envelope well. They should differ
in strategy -- for example maximising unit count, maximising unit size, or
leaving more open space for a better street presence -- not merely in name.

For each concept return:
- option_name: short, descriptive
- rationale: 1-2 sentences on the trade-off it makes
- building_area_sft: total gross floor area, at or below the maximum above
- floors: at or below the maximum above
- units_per_floor: integer
- avg_unit_sf: integer
- layout: {{"footprint": [[x, y], ...], "stairs": [[[x, y], ...]]}}

The footprint polygon must lie inside the buildable bounding box given above
and use the same plane-feet coordinates. Keep it rectangular or simply
L-shaped. Its area times floors must not exceed the maximum gross floor area.

Respond with a JSON object holding a list under the key "options"."""

    body = {
        "model": GROQ_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an architectural programming assistant. A rule engine "
                    "supplies the zoning limits; you allocate space within them. "
                    "Never exceed a stated maximum. Always respond with valid JSON."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        # Deterministic generation. The envelope is already fixed, so there is
        # no reason for the allocation to wander between runs on the same input.
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }

    try:
        response = requests.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=60,
        )
        try:
            result = response.json()
        except ValueError:
            return json.dumps({"error": "Groq API returned invalid JSON"})

        if "choices" not in result:
            return json.dumps(
                {"error": "Groq API did not return 'choices'. Response: " + str(result)}
            )
        return result["choices"][0]["message"]["content"]
    except requests.RequestException as e:
        return json.dumps({"error": str(e)})
