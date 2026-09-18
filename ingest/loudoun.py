"""Readers for the Loudoun County GIS CSV exports.

These exports carry attributes and shape *measurements* but no polygon
geometry -- see reference/loudoun-gis/README.md. What they do support is a
parcel index (id, legal area, perimeter, centroid) and an authoritative
district catalog. Everything here is deliberately explicit about which of
those two it is giving you.
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from engine.parcel import Parcel

REFERENCE = Path(__file__).resolve().parent.parent / "reference" / "loudoun-gis"
JURISDICTION = "Loudoun County, VA"

# The county writes empty cells as a single space in several columns.
def _clean(value: str | None) -> str:
    return (value or "").strip()


# Parcel IDs are 12-character zero-padded strings. Excel treats them as numbers,
# which strips the leading zeros and, past 11 digits, replaces the value with
# 3-significant-figure scientific notation. Both happened to this export.
MCPI_WIDTH = 12
_SCIENTIFIC = re.compile(r"^[\d.]+E\+\d+$", re.IGNORECASE)


def normalize_mcpi(value: str | None) -> str | None:
    """Restore a parcel ID Excel has mangled, or None if it is unrecoverable.

    Leading zeros can be put back by padding. Scientific notation cannot be
    undone -- '2.17E+11' has lost nine digits -- so it returns None rather than
    inventing an ID that would join to the wrong parcel.
    """
    text = _clean(value)
    if not text:
        return None
    if _SCIENTIFIC.match(text):
        return None
    if not text.isdigit():
        return None
    return text.zfill(MCPI_WIDTH)


@dataclass(frozen=True)
class LoadReport:
    """What the reader had to throw away, and why."""

    rows: int = 0
    loaded: int = 0
    blank_ids: int = 0
    destroyed_ids: int = 0
    no_perimeter: int = 0

    def describe(self) -> str:
        lines = [f"{self.loaded:,} of {self.rows:,} rows usable"]
        if self.destroyed_ids:
            lines.append(
                f"{self.destroyed_ids:,} parcel IDs unrecoverable (Excel wrote them "
                f"as scientific notation, losing all but 3 significant digits) -- "
                f"re-export with the ID column typed as text"
            )
        if self.blank_ids:
            lines.append(f"{self.blank_ids:,} rows had no parcel ID")
        if self.no_perimeter:
            lines.append(f"{self.no_perimeter:,} rows had no perimeter to fit a shape to")
        return "; ".join(lines)


def _number(value: str | None) -> float | None:
    text = _clean(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


@dataclass(frozen=True)
class ParcelRecord:
    """One row of the parcel table. No boundary -- see module docstring."""

    mcpi: str
    legal_acres: float | None
    legal_sqft: float | None
    shape_area_sf: float | None
    shape_perimeter_ft: float | None
    subdivision: str | None = None
    plat_lot: str | None = None

    @property
    def area_sf(self) -> float | None:
        """Best available area.

        SHAPE_Area is the measured area of the mapped polygon and is what the
        perimeter belongs to, so it is preferred: mixing a legal area with a
        mapped perimeter would fit a rectangle to two numbers that describe
        different outlines.
        """
        return self.shape_area_sf or self.legal_sqft

    def to_parcel(self, **kwargs) -> Parcel:
        """An equivalent-rectangle Parcel. Assumed shape; see Parcel docs."""
        if self.area_sf is None:
            raise ValueError(f"parcel {self.mcpi}: no area recorded")
        if not self.shape_perimeter_ft:
            raise ValueError(
                f"parcel {self.mcpi}: no perimeter recorded, so no shape can be "
                f"fitted; only the area is known"
            )
        kwargs.setdefault("jurisdiction", JURISDICTION)
        return Parcel.from_area_and_perimeter(
            parcel_id=self.mcpi,
            area_sf=self.area_sf,
            perimeter_ft=self.shape_perimeter_ft,
            **kwargs,
        )


@dataclass(frozen=True)
class Centroid:
    """A parcel's centre point. Not a boundary."""

    mcpi: str
    lon: float
    lat: float
    state_plane_x: float | None = None
    state_plane_y: float | None = None


@dataclass(frozen=True)
class DistrictRecord:
    """A zoning district as the county's own layer describes it."""

    code: str
    ordinance: str
    name: str
    description: str
    parcel_count: int = 0

    @property
    def key(self) -> str:
        """Districts are identified by code AND ordinance.

        The same code can exist under two ordinances with different standards,
        so a bundle keyed on the code alone would silently mix them.
        """
        return f"{self.code}-{self.ordinance}"


def load_parcels(
    path: str | Path | None = None,
) -> tuple[dict[str, ParcelRecord], LoadReport]:
    """Read the parcel table, returning the records and what was lost.

    The report is returned rather than logged because the loss here is large
    enough to change what you can conclude: most of this export's parcel IDs
    cannot be joined to anything.
    """
    path = Path(path or REFERENCE / "sample_Loudoun_Parcels.csv")
    out: dict[str, ParcelRecord] = {}
    rows = blank = destroyed = no_perimeter = 0

    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            rows += 1
            raw = _clean(row.get("PA_MCPI"))
            mcpi = normalize_mcpi(raw)
            if mcpi is None:
                if raw:
                    destroyed += 1
                else:
                    blank += 1
                continue
            if not _number(row.get("SHAPE_Length")):
                no_perimeter += 1
            out[mcpi] = ParcelRecord(
                mcpi=mcpi,
                legal_acres=_number(row.get("PA_LEGAL_ACRE")),
                legal_sqft=_number(row.get("PA_LEGAL_SQFT")),
                shape_area_sf=_number(row.get("SHAPE_Area")),
                shape_perimeter_ft=_number(row.get("SHAPE_Length")),
                subdivision=_clean(row.get("PA_SUBD_NAME")) or None,
                plat_lot=_clean(row.get("PA_PLAT_LOT")) or None,
            )
    return out, LoadReport(
        rows=rows,
        loaded=len(out),
        blank_ids=blank,
        destroyed_ids=destroyed,
        no_perimeter=no_perimeter,
    )


def load_centroids(path: str | Path | None = None) -> dict[str, Centroid]:
    path = Path(path or REFERENCE / "sample_Loudoun_Parcel_Coordinates.csv")
    out: dict[str, Centroid] = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            mcpi = normalize_mcpi(row.get("PA_MCPI"))
            lon, lat = _number(row.get("POINT_X")), _number(row.get("POINT_Y"))
            if mcpi is None or lon is None or lat is None:
                continue
            out[mcpi] = Centroid(
                mcpi=mcpi,
                lon=lon,
                lat=lat,
                state_plane_x=_number(row.get("POINT_X_SP")),
                state_plane_y=_number(row.get("POINT_Y_SP")),
            )
    return out


def load_districts(path: str | Path | None = None) -> dict[str, DistrictRecord]:
    """The district catalog, keyed by code-and-ordinance.

    The layer has one row per mapped zoning polygon, so districts repeat. The
    longest description is kept, on the assumption that a truncated or blank
    one is the less complete record rather than a different district.
    """
    path = Path(path or REFERENCE / "Loudoun_Zoning.csv")
    best: dict[str, DistrictRecord] = {}
    counts: dict[str, int] = defaultdict(int)

    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            code = _clean(row.get("ZO_ZONE"))
            if not code:
                continue
            ordinance = _clean(row.get("ZO_ORDINANCE")) or "unknown"
            key = f"{code}-{ordinance}"
            counts[key] += 1
            record = DistrictRecord(
                code=code,
                ordinance=ordinance,
                name=_clean(row.get("ZD_ZONE_NAME")),
                description=_clean(row.get("ZD_ZONE_DESC")),
                parcel_count=0,
            )
            existing = best.get(key)
            if existing is None or len(record.description) > len(existing.description):
                best[key] = record

    return {
        key: DistrictRecord(
            code=r.code,
            ordinance=r.ordinance,
            name=r.name,
            description=r.description,
            parcel_count=counts[key],
        )
        for key, r in best.items()
    }
