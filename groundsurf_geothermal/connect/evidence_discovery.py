"""Deterministic discovery, independent of optional language models."""

import datetime
import math
import re
from urllib.parse import urlencode

from .inference import request

BGR = "https://services.bgr.de/arcgis/rest/services/geologie/gbl/MapServer/2"
BGR_TERMS = "https://www.bgr.bund.de/AGB_en"
BGR_CREDIT = "Datenquelle: GBL, (c) Staatliche Geologische Dienste, 2016"
MAX_RECORDS = 2000
REGIONS = [
    (
        "Germany",
        (5.4, 46.9, 15.7, 55.1),
        "BGR Borehole Map",
        "https://boreholemap.bgr.de/",
        {"boreholes", "geology"},
    ),
    (
        "Poland",
        (14.1, 49, 24.2, 54.9),
        "PGI-PIB / CBDG",
        "https://ogcapi.pgi.gov.pl",
        {"boreholes", "geology", "groundwater"},
    ),
    (
        "Denmark",
        (8, 54.5, 15.3, 58),
        "GEUS Jupiter / GEUS maps",
        "https://data.geus.dk/geusmap/",
        {"boreholes", "geology", "groundwater"},
    ),
    (
        "Netherlands",
        (3.2, 50.7, 7.3, 53.7),
        "BRO geotechnical boreholes",
        "https://publiek.broservices.nl/sr/bhrgt/v2/objects/",
        {"boreholes"},
    ),
    (
        "Belgium",
        (2.5, 49.5, 6.5, 51.6),
        "DOV Flanders",
        "https://www.dov.vlaanderen.be/",
        {"boreholes", "geology", "groundwater", "cpt"},
    ),
    (
        "France",
        (-5.2, 41, 8.4, 51.2),
        "BRGM InfoTerre / BSS",
        "https://infoterre.brgm.fr/",
        {"boreholes", "geology", "groundwater"},
    ),
    (
        "United Kingdom",
        (-9, 49, 2, 61),
        "BGS GeoIndex",
        "https://www.bgs.ac.uk/map-viewers/geoindex-onshore/",
        {"boreholes", "geology"},
    ),
]
TERRAIN = {"terrain", "imagery"}


def classify(text):
    text = text.casefold()
    # Recover common missing spaces between an action and a data type.
    text = re.sub(
        r"\b(download|find|get|fetch|import|show|search|acquire|retrieve)"
        r"(?=borehole|bore hole|terrain|imagery|aerial|groundwater|geolog|cpt|geophys)",
        r"\1 ",
        text,
    )
    patterns = {
        "terrain": r"\b(terrain|elevation|topograph\w*|dtm|dem|dsm|landscape|gelände|nmt|rzeźb\w*)\b",
        "imagery": r"\b(imag\w*|aerial|satellite|orthophoto\w*|photo\w*|landscape|luftbild\w*|orto\w*)\b",
        "boreholes": r"\b(borehole\w*|bore hole\w*|drill\w*|well\w*|bohr\w*|odwiert\w*|otwor\w*|otwór\w*)\b",
        "geology": r"\b(geolog\w*|stratigraph\w*|litholog\w*)\b",
        "groundwater": r"\b(groundwater|hydrogeolog\w*|grundwasser\w*|wod\w* podziemn\w*)\b",
        "cpt": r"\b(cpt\w*|cone penetration|sondow\w*)\b",
        "geophysics": r"\b(geophys\w*|seismic\w*|geofiz\w*)\b",
    }
    return {role for role, pattern in patterns.items() if re.search(pattern, text)}


def intersects(a, b):
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def portals(bounds, roles):
    return [
        (region, name, url)
        for region, bbox, name, url, types in REGIONS
        if intersects(bounds, bbox) and roles.intersection(types)
    ]


def supports_bgr(bounds):
    return intersects(bounds, REGIONS[0][1])


def query_bgr(bounds, cancel=lambda: False):
    if (
        len(bounds) != 4
        or not all(math.isfinite(v) for v in bounds)
        or not -180 <= bounds[0] < bounds[2] <= 180
        or not -90 <= bounds[1] < bounds[3] <= 90
        or bounds[2] - bounds[0] > 1
        or bounds[3] - bounds[1] > 1
    ):
        raise ValueError(
            "Choose a smaller local area for borehole discovery (up to 1° in each direction)."
        )
    if not supports_bgr(bounds):
        raise ValueError("The German BGR register is not a match for this area.")
    if cancel():
        raise InterruptedError("Search cancelled.")
    params = dict(
        where="1=1",
        geometry=",".join(str(v) for v in bounds),
        geometryType="esriGeometryEnvelope",
        inSR="4326",
        spatialRel="esriSpatialRelIntersects",
        outFields="OBJECTID,gml_ID,totalLength,SGD,MERGE_SRC",
        returnGeometry="true",
        outSR="4326",
        resultRecordCount=str(MAX_RECORDS),
        orderByFields="OBJECTID",
        f="geojson",
    )
    url = BGR + "/query?" + urlencode(params)
    data = request(url, timeout=30)
    if cancel():
        raise InterruptedError("Search cancelled.")
    if (
        data.get("error")
        or data.get("type") != "FeatureCollection"
        or not isinstance(data.get("features"), list)
    ):
        raise ValueError("BGR did not return a valid borehole collection. Coverage is unknown.")
    rows = data["features"]
    limited = bool(
        data.get("exceededTransferLimit")
        or (data.get("properties") or {}).get("exceededTransferLimit")
        or len(rows) >= MAX_RECORDS
    )
    retrieved = datetime.datetime.now(datetime.timezone.utc).isoformat()
    features, seen = [], set()
    invalid = 0
    for row in rows[:MAX_RECORDS]:
        geom = row.get("geometry") or {}
        xy = geom.get("coordinates")
        p = row.get("properties") or {}
        if (
            geom.get("type") != "Point"
            or not isinstance(xy, list)
            or len(xy) != 2
            or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in xy)
            or not bounds[0] <= xy[0] <= bounds[2]
            or not bounds[1] <= xy[1] <= bounds[3]
        ):
            invalid += 1
            continue
        ident = p.get("gml_ID")
        if not isinstance(ident, str) or not ident.strip():
            invalid += 1
            continue
        oid = p.get("OBJECTID")
        key = (ident, tuple(xy))
        if key in seen:
            continue
        seen.add(key)
        depth = p.get("totalLength")
        if not isinstance(depth, (int, float)) or not math.isfinite(depth) or depth < 0:
            depth = None
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": xy},
                "properties": {
                    "borehole_id": ident,
                    "object_id": oid,
                    "reported_length_m": depth,
                    "survey": str(p.get("SGD") or ""),
                    "original_source": str(p.get("MERGE_SRC") or ""),
                    "source": BGR,
                    "attribution": BGR_CREDIT,
                    "terms": BGR_TERMS,
                    "retrieved_utc": retrieved,
                    "record_type": "location_and_header",
                    "intervals_available": None,
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
        "groundsurf": {
            "source": BGR,
            "query_url": url,
            "query_bounds_wgs84": list(bounds),
            "retrieved_utc": retrieved,
            "attribution": BGR_CREDIT,
            "terms": BGR_TERMS,
            "record_limit": MAX_RECORDS,
            "limit_reached": limited,
            "invalid_records": invalid,
            "limitations": "Location/header only; no collar elevation, stratigraphy or groundwater readings.",
        },
    }
