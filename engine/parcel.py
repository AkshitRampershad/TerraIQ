"""Parcel geometry and the lot-line classification the setback rules need.

Coordinates are plane feet (a local survey plane such as Virginia State Plane
North, EPSG:2283). They are deliberately not lat/lon: setbacks are linear
distances, and measuring them in degrees is wrong by a factor that varies with
latitude. Projection happens upstream of this module.

Every edge of the parcel ring carries a classification, because zoning
prescribes a different setback for a front lot line than for a rear or an
interior side line. Getting that assignment right is a survey/GIS question,
not a geometry question, so `Parcel` records where the assignment came from
and the report repeats it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry


class EdgeKind(str, Enum):
    """How a lot line is classified for setback purposes."""

    FRONT = "front"
    REAR = "rear"
    SIDE_INTERIOR = "side_interior"
    SIDE_STREET = "side_street"

    @property
    def setback_rule_key(self) -> str:
        return f"setback_{self.value}"


class OverlayKind(str, Enum):
    EASEMENT = "easement"
    FLOODWAY = "floodway"
    WETLAND = "wetland"
    RIGHT_OF_WAY = "right_of_way"
    HISTORIC = "historic"
    UTILITY = "utility"
    OTHER = "other"


@dataclass(frozen=True)
class Overlay:
    """A mapped area that constrains or forbids building.

    `buildable=False` removes the area from the envelope outright. An overlay
    that merely adds design review (a historic district, say) is recorded with
    `buildable=True` so it surfaces in the report without shrinking the
    envelope -- the engine never silently drops a constraint it cannot model.
    """

    name: str
    kind: OverlayKind
    coords: list[tuple[float, float]]
    citation: str
    buildable: bool = False
    source: str | None = None

    def __post_init__(self) -> None:
        if not self.buildable and len(self.coords) < 3:
            raise ValueError(
                f"overlay {self.name!r} removes area from the envelope but has "
                f"fewer than 3 vertices"
            )

    @property
    def polygon(self) -> Polygon:
        return Polygon(self.coords)


@dataclass
class Parcel:
    """A lot, its boundary, and how that boundary was classified."""

    parcel_id: str
    coords: list[tuple[float, float]]
    edge_kinds: list[EdgeKind]
    address: str | None = None
    jurisdiction: str | None = None
    zoning_district: str | None = None
    overlays: list[Overlay] = field(default_factory=list)
    geometry_source: str = "unspecified"
    edge_classification_source: str = "unspecified"
    is_assumed_shape: bool = False

    def __post_init__(self) -> None:
        if len(self.coords) < 3:
            raise ValueError(f"parcel {self.parcel_id!r} needs at least 3 vertices")
        if self.coords[0] == self.coords[-1]:
            self.coords = self.coords[:-1]
        if len(self.edge_kinds) != len(self.coords):
            raise ValueError(
                f"parcel {self.parcel_id!r}: {len(self.coords)} edges but "
                f"{len(self.edge_kinds)} edge classifications -- every lot line "
                f"needs one, because each takes a different setback"
            )
        if not self.polygon.is_valid:
            raise ValueError(
                f"parcel {self.parcel_id!r}: boundary is self-intersecting; "
                f"clean the geometry before analysis"
            )

    @property
    def polygon(self) -> Polygon:
        return Polygon(self.coords)

    @property
    def area_sf(self) -> float:
        return self.polygon.area

    @property
    def area_acres(self) -> float:
        return self.area_sf / 43_560.0

    @property
    def perimeter_ft(self) -> float:
        return self.polygon.length

    def edges(self) -> list[tuple[LineString, EdgeKind]]:
        """Each lot line paired with its classification, in ring order."""
        ring = list(self.coords) + [self.coords[0]]
        return [
            (LineString([ring[i], ring[i + 1]]), self.edge_kinds[i])
            for i in range(len(self.coords))
        ]

    def frontage_ft(self) -> float:
        """Total length of lot lines classified as front.

        Used for the minimum-lot-width test. This is street frontage, which
        equals lot width only on a regular lot; an irregular or flag lot needs
        the jurisdiction's own width definition, which varies enough that the
        engine reports the measure it used rather than guessing.
        """
        return sum(
            line.length for line, kind in self.edges() if kind is EdgeKind.FRONT
        )

    def no_build_overlays(self) -> list[Overlay]:
        return [o for o in self.overlays if not o.buildable]

    def advisory_overlays(self) -> list[Overlay]:
        """Overlays that constrain the project but not the envelope geometry."""
        return [o for o in self.overlays if o.buildable]

    @classmethod
    def assumed_rectangle(
        cls,
        parcel_id: str,
        area_sf: float,
        frontage_ft: float | None = None,
        *,
        address: str | None = None,
        jurisdiction: str | None = None,
        zoning_district: str | None = None,
        depth_to_width: float = 2.5,
    ) -> Parcel:
        """Build a stand-in rectangular lot from an area figure alone.

        This exists because a typed-in acreage carries no shape, and setbacks
        cannot be computed without one. The result is explicitly flagged
        `is_assumed_shape`, and the report refuses to present its numbers as
        anything but an illustration. A real analysis needs the parcel polygon
        from the county's GIS.

        The rectangle is oriented with its short side on the street, matching
        the usual platting pattern; `depth_to_width` controls how deep.
        """
        if area_sf <= 0:
            raise ValueError("parcel area must be positive")
        if frontage_ft is not None and frontage_ft > 0:
            width = float(frontage_ft)
            depth = area_sf / width
        else:
            width = math.sqrt(area_sf / depth_to_width)
            depth = area_sf / width

        return cls(
            parcel_id=parcel_id,
            coords=[(0.0, 0.0), (width, 0.0), (width, depth), (0.0, depth)],
            # Ring order: street edge, one side, rear, other side.
            edge_kinds=[
                EdgeKind.FRONT,
                EdgeKind.SIDE_INTERIOR,
                EdgeKind.REAR,
                EdgeKind.SIDE_INTERIOR,
            ],
            address=address,
            jurisdiction=jurisdiction,
            zoning_district=zoning_district,
            geometry_source="ASSUMED rectangle derived from a stated lot area",
            edge_classification_source="ASSUMED (short side presumed to front the street)",
            is_assumed_shape=True,
        )


def polygon_coords(geom: BaseGeometry) -> list[list[tuple[float, float]]]:
    """Exterior rings of a polygon or multipolygon, for plotting."""
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [list(geom.exterior.coords)]
    if geom.geom_type == "MultiPolygon":
        return [list(part.exterior.coords) for part in geom.geoms]
    return []
