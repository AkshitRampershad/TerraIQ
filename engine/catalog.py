"""Lookup from a jurisdiction's district code to its rule bundle.

Two behaviours here matter more than the lookup itself.

When no bundle exists for a district, the engine says so and stops. It does not
fall back to a "typical" district and it does not ask a model to recall the
standards -- an invented setback is worse than no answer, because it looks like
an answer.

When a district code exists under more than one ordinance, the engine refuses
to choose. Loudoun has three such codes (PDH3, PDH6, PDRDP): parcels zoned
under the 1972 ordinance and the 2023 ordinance carry the same label and
different standards. Picking the newer one silently would analyse a legacy
parcel against rules that do not apply to it.
"""

from __future__ import annotations

import re
from pathlib import Path

from engine.rules import RuleBundle, RuleError

DATA_ROOT = Path(__file__).resolve().parent.parent / "reference" / "districts"


class DistrictNotOnFile(RuleError):
    """No rule bundle exists for this district."""


class AmbiguousDistrict(RuleError):
    """The code exists under several ordinances; the caller must say which."""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")


def normalize_district(code: str) -> str:
    """Normalize a district code for matching.

    Jurisdictions write the same district as 'R16', 'R-16' or 'R 16'. Loudoun's
    GIS uses the unhyphenated form. Matching strips separators entirely so any
    spelling resolves to the same bundle.
    """
    return re.sub(r"[\s\-_]+", "", (code or "").strip().upper())


def _folder_for(jurisdiction: str) -> Path | None:
    """Resolve a jurisdiction name to its data folder, tolerating variants."""
    slug = _slug(jurisdiction)
    for candidate in (slug, slug.replace("-county", ""), slug.replace("county-", "")):
        folder = DATA_ROOT / candidate
        if folder.is_dir():
            return folder
    return None


def _index(folder: Path) -> dict[str, dict[str, Path]]:
    """normalized district code -> {ordinance: path}.

    Files are named `<CODE>@<ORDINANCE>.json`; a bare `<CODE>.json` is treated
    as having an unspecified ordinance.
    """
    out: dict[str, dict[str, Path]] = {}
    for path in sorted(folder.glob("*.json")):
        if path.stem.startswith("_"):
            continue
        code, _, ordinance = path.stem.partition("@")
        out.setdefault(normalize_district(code), {})[ordinance or "unspecified"] = path
    return out


def available_districts(jurisdiction: str) -> list[str]:
    """Every district on file, as `CODE (ordinance)` strings."""
    folder = _folder_for(jurisdiction)
    if folder is None:
        return []
    return sorted(
        f"{code} ({ordinance})"
        for code, by_ord in _index(folder).items()
        for ordinance in by_ord
    )


def available_codes(jurisdiction: str) -> list[str]:
    folder = _folder_for(jurisdiction)
    return sorted(_index(folder)) if folder else []


def iter_bundles(jurisdiction: str):
    """Yield (code, ordinance, bundle) for every bundle on file."""
    folder = _folder_for(jurisdiction)
    if folder is None:
        return
    for code, by_ordinance in sorted(_index(folder).items()):
        for ordinance, path in sorted(by_ordinance.items()):
            yield code, ordinance, RuleBundle.from_json(path)


def load_bundle(
    jurisdiction: str, district: str, ordinance: str | None = None
) -> RuleBundle:
    """Load the rule bundle for a district, or explain why we cannot."""
    folder = _folder_for(jurisdiction)
    code = normalize_district(district)
    index = _index(folder) if folder is not None else {}

    if code not in index:
        known = available_codes(jurisdiction)
        raise DistrictNotOnFile(
            f"No rule bundle on file for {jurisdiction} district {code!r}. "
            + (
                f"Districts available: {', '.join(known)}."
                if known
                else f"No districts are on file for {jurisdiction}."
            )
            + " Add one from reference/districts/_TEMPLATE.json, transcribed from "
            "the published ordinance. The engine will not guess a district's "
            "standards."
        )

    by_ordinance = index[code]

    if ordinance is not None:
        wanted = str(ordinance).strip()
        if wanted not in by_ordinance:
            raise DistrictNotOnFile(
                f"{jurisdiction} district {code} has no bundle for the "
                f"{wanted!r} ordinance. On file: {', '.join(sorted(by_ordinance))}."
            )
        return RuleBundle.from_json(by_ordinance[wanted])

    if len(by_ordinance) > 1:
        raise AmbiguousDistrict(
            f"{jurisdiction} district {code} exists under more than one ordinance "
            f"({', '.join(sorted(by_ordinance))}), and their standards differ. "
            f"Pass the ordinance explicitly -- the parcel's zoning record carries "
            f"it in ZO_ORDINANCE. The engine will not pick one for you."
        )

    return RuleBundle.from_json(next(iter(by_ordinance.values())))
