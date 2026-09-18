import requests

# Loudoun County retired maps.loudoun.gov and moved its GIS REST services to
# logis.loudoun.gov. The zoning polygon layer also moved from
# Public/Zoning/MapServer/7 to COL/Zoning/MapServer/3 ("Zoning", the
# current official zoning map, fields include ZO_ZONE/ZO_ORDINANCE/etc).
ZONING_QUERY_URL = "https://logis.loudoun.gov/gis/rest/services/COL/Zoning/MapServer/3/query"


def get_zoning_info(lat, lon):
    try:
        params = {
            "f": "json",
            "geometryType": "esriGeometryPoint",
            "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
            "geometry": f"{lon},{lat}",
            "outFields": "*",
        }

        response = requests.get(ZONING_QUERY_URL, params=params, timeout=15)

        if response.status_code != 200:
            return {"error": f"Loudoun API returned status {response.status_code}"}

        try:
            data = response.json()
        except ValueError:
            return {"error": "Invalid JSON from Loudoun County API"}

        if not data.get("features"):
            return {"error": "No zoning info found for this location."}

        return data["features"][0]["attributes"]

    except Exception as e:
        return {"error": str(e)}


# Field names vary between ArcGIS layers and between ordinance revisions, so
# the district code is looked up by trying the known candidates in order
# rather than hard-coding one. If none matches, the caller is told which keys
# were actually present -- far more useful than a silent None.
DISTRICT_FIELDS = (
    "ZO_ZONE",
    "ZONING",
    "ZONE",
    "ZO_ZONE_DESC",
    "ZONE_CODE",
    "ZONING_DISTRICT",
)


def district_from_attributes(attributes):
    """Pull the zoning district code out of an ArcGIS attribute dictionary.

    Returns (district_code, field_name) or (None, None).
    """
    if not isinstance(attributes, dict):
        return None, None
    for field in DISTRICT_FIELDS:
        value = attributes.get(field)
        if value not in (None, "", " "):
            return str(value).strip(), field
    return None, None
