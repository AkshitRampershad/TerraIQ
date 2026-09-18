"""Human-readable rendering of an envelope and its program.

The report's job is to make the analysis reviewable: every number names the
rule that produced it, every rule names its code section, and anything the
engine assumed rather than computed is called out rather than buried.
"""

from __future__ import annotations

from engine.envelope import Envelope, Finding
from engine.program import Program

_SEVERITY_MARK = {"blocker": "[BLOCKER]", "warning": "[WARNING]", "info": "[note]"}


def _fmt(value: float | None, unit: str = "", digits: int = 0) -> str:
    if value is None:
        return "not determined"
    return f"{value:,.{digits}f}{(' ' + unit) if unit else ''}"


def _findings_block(findings: list[Finding]) -> list[str]:
    if not findings:
        return []
    order = {"blocker": 0, "warning": 1, "info": 2}
    lines = []
    for f in sorted(findings, key=lambda x: order[x.severity]):
        lines.append(f"{_SEVERITY_MARK[f.severity]} {f.title}")
        lines.append(f"    {f.detail}")
        if f.citation:
            lines.append(f"    Source: {f.citation}")
        lines.append("")
    return lines


def render_report(envelope: Envelope, program: Program | None = None) -> str:
    """Render the full analysis as plain text."""
    p = envelope.parcel
    b = envelope.bundle
    out: list[str] = []

    out.append("=" * 72)
    out.append("TerraIQ -- Zoning Envelope Analysis")
    out.append("=" * 72)
    out.append("")
    out.append(f"Parcel:       {p.parcel_id}" + (f"  ({p.address})" if p.address else ""))
    out.append(f"Jurisdiction: {b.jurisdiction}")
    out.append(f"District:     {b.district} -- {b.district_name}")
    out.append(f"Code version: {b.code_version}, effective {b.effective_date}")
    out.append(f"Lot area:     {_fmt(p.area_sf, 'sf')} ({p.area_acres:,.3f} acres)")
    out.append(f"Frontage:     {_fmt(p.frontage_ft(), 'ft', 1)}")
    out.append(f"Geometry:     {p.geometry_source}")
    out.append(f"Lot lines:    {p.edge_classification_source}")
    out.append("")

    if not b.fully_verified:
        out.append("-" * 72)
        out.append("!! THESE STANDARDS ARE NOT VERIFIED AGAINST THE PUBLISHED ORDINANCE.")
        out.append("!! The figures below demonstrate the method. They are not a zoning")
        out.append("!! determination and must not be relied on for design or submittal.")
        out.append("-" * 72)
        out.append("")

    out.append("BUILDABLE ENVELOPE")
    out.append("-" * 72)
    out.append(f"  Buildable area          {_fmt(envelope.buildable_area_sf, 'sf')} "
               f"({envelope.buildable_fraction:.0%} of the lot)")
    out.append(f"  Lost to setbacks        {_fmt(envelope.area_lost_to_setbacks_sf, 'sf')}")
    out.append(f"  Lost to overlays        {_fmt(envelope.area_lost_to_overlays_sf, 'sf')}")
    out.append(f"  Largest contiguous      {_fmt(envelope.largest_contiguous_sf, 'sf')}")
    out.append(f"  Max footprint           {_fmt(envelope.max_footprint_sf, 'sf')}")
    out.append(f"  Max single building     {_fmt(envelope.max_single_building_sf, 'sf')}")
    out.append(f"  Stories                 {envelope.stories if envelope.stories is not None else 'not limited on file'}")
    out.append(f"  Height                  {_fmt(envelope.height_ft, 'ft')}")
    out.append("")

    if program is not None:
        out.append("PROGRAM")
        out.append("-" * 72)
        out.append(f"  Gross floor area        {_fmt(program.gross_floor_area_sf, 'sf')}")
        far_text = (
            f"{program.far_achieved:.2f}"
            if program.far_achieved is not None
            else "not determined"
        )
        out.append(f"  FAR achieved            {far_text}")
        out.append(f"  Dwelling units          "
                   f"{program.units if program.units is not None else 'not determined'}")
        out.append(f"  Parking required        "
                   f"{program.parking_required if program.parking_required is not None else 'not determined'}")
        if program.parking_fits is not None:
            out.append(f"  Surface parking fits    {'yes' if program.parking_fits else 'NO'}")
        out.append(f"  Binding constraint      {program.binding_constraint}")
        out.append("")

    out.append("HOW EACH NUMBER WAS DETERMINED")
    out.append("-" * 72)
    all_dets = list(envelope.determinations) + (
        list(program.determinations) if program else []
    )
    for d in all_dets:
        out.append(f"  {d.quantity}: {_fmt(d.value, d.unit)}")
        out.append(f"    Bound by: {d.driver}")
        if d.detail:
            out.append(f"    {d.detail}")
        if d.citation:
            out.append(f"    Authority: {d.citation}")
        if d.alternatives:
            pairs = ", ".join(f"{k} = {v:,.0f}" for k, v in d.alternatives.items())
            out.append(f"    Caps considered: {pairs}")
        out.append("")

    findings = list(envelope.findings) + (list(program.findings) if program else [])
    if findings:
        out.append("FINDINGS")
        out.append("-" * 72)
        out.extend(_findings_block(findings))

    if program is not None:
        out.append("MODELLING ASSUMPTIONS (not zoning requirements)")
        out.append("-" * 72)
        for line in program.assumptions.describe():
            out.append(f"  {line}")
        out.append("")

    out.append("STANDARDS APPLIED")
    out.append("-" * 72)
    for key in sorted(b.rules):
        out.append(f"  {b.rules[key]}")
        cite = b.rules[key].citation
        if cite:
            out.append(f"      {cite}")
    out.append("")
    out.append("This analysis is produced by a deterministic rule engine, not a")
    out.append("language model. It is not a zoning determination and does not")
    out.append("substitute for review by a licensed architect or the jurisdiction.")
    return "\n".join(out)
