"""Site plan rendering: lot, setbacks, buildable envelope, proposed building.

Drawing the envelope rather than only the proposed footprint is deliberate.
The useful thing to look at is not the building on its own but the building
against what the ordinance allows -- the gap between them is the design
conversation.
"""

import plotly.graph_objects as go

from engine.parcel import polygon_coords

LOT_LINE = "#1f2d3d"
BUILDABLE_FILL = "rgba(45, 156, 219, 0.28)"
BUILDABLE_LINE = "#2d9cdb"
BUILDING_FILL = "rgba(235, 87, 87, 0.55)"
BUILDING_LINE = "#c0392b"
OVERLAY_FILL = "rgba(242, 153, 74, 0.35)"
OVERLAY_LINE = "#f2994a"


def _add_ring(fig, ring, *, name, fill, line, dash=None, showlegend=True):
    if not ring:
        return
    x, y = zip(*ring)
    fig.add_trace(
        go.Scatter(
            x=list(x),
            y=list(y),
            fill="toself" if fill else None,
            fillcolor=fill,
            name=name,
            mode="lines",
            line=dict(color=line, dash=dash, width=2),
            showlegend=showlegend,
            hoverinfo="name",
        )
    )


def plot_site(envelope, footprint=None, title="Site plan"):
    """Render the parcel, its buildable envelope, and an optional footprint."""
    fig = go.Figure()

    lot = list(envelope.parcel.polygon.exterior.coords)
    _add_ring(fig, lot, name="Lot boundary", fill=None, line=LOT_LINE)

    for overlay in envelope.parcel.no_build_overlays():
        _add_ring(
            fig,
            list(overlay.polygon.exterior.coords),
            name=f"No-build: {overlay.name}",
            fill=OVERLAY_FILL,
            line=OVERLAY_LINE,
            dash="dot",
        )

    for i, ring in enumerate(polygon_coords(envelope.buildable)):
        _add_ring(
            fig,
            ring,
            name="Buildable envelope",
            fill=BUILDABLE_FILL,
            line=BUILDABLE_LINE,
            showlegend=(i == 0),
        )

    if footprint and len(footprint) >= 3:
        ring = [(float(x), float(y)) for x, y in footprint]
        ring.append(ring[0])
        _add_ring(fig, ring, name="Proposed building", fill=BUILDING_FILL, line=BUILDING_LINE)

    fig.update_layout(
        title=title,
        xaxis=dict(scaleanchor="y", showgrid=False, title="feet"),
        yaxis=dict(showgrid=False, title="feet"),
        margin=dict(l=10, r=10, t=40, b=10),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def plot_layout(layout_json):
    """Footprint-only rendering, kept for callers without an envelope."""
    fig = go.Figure()
    if "footprint" in layout_json:
        ring = [(float(x), float(y)) for x, y in layout_json["footprint"]]
        ring.append(ring[0])
        _add_ring(fig, ring, name="Footprint", fill=BUILDING_FILL, line=BUILDING_LINE)
    for idx, stair in enumerate(layout_json.get("stairs", []) or []):
        try:
            ring = [(float(x), float(y)) for x, y in stair]
        except (TypeError, ValueError):
            continue
        ring.append(ring[0])
        _add_ring(fig, ring, name=f"Stair {idx + 1}", fill=None, line="gray", dash="dot")
    fig.update_layout(
        title="Proposed building layout",
        xaxis=dict(scaleanchor="y", showgrid=False),
        yaxis=dict(showgrid=False),
        margin=dict(l=10, r=10, t=40, b=10),
        showlegend=True,
    )
    return fig
