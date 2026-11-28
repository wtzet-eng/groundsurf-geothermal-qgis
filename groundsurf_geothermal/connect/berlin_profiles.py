"""Berlin regional borehole evidence. Profile links are not interpreted intervals."""

import datetime
import math
import re
from urllib.parse import urlencode, urlsplit, parse_qs
from .inference import request

BERLIN = "https://gdi.berlin.de/services/wfs/bohrdaten"
CREDIT = "Senatsverwaltung für Mobilität, Verkehr, Klimaschutz und Umwelt Berlin"
TERMS = "https://daten.berlin.de/datensaetze/geologische-bohrdaten-wfs-e246e572"
LIMIT = 500


def supports_berlin(bounds):
    # Regional envelope, not an administrative boundary or a coverage guarantee.
    return (
        len(bounds) == 4
        and 13.08 <= bounds[0] < bounds[2] <= 13.77
        and 52.32 <= bounds[1] < bounds[3] <= 52.70
        and bounds[2] - bounds[0] <= 0.15
        and bounds[3] - bounds[1] <= 0.15
    )


def profile_url(value):
    if not isinstance(value, str) or len(value) > 512:
        return None
    try:
        p = urlsplit(value)
        if (p.scheme, p.netloc, p.path, p.fragment) != (
            "https",
            "gdi.berlin.de",
            "/ext/bohrungen/getimage",
            "",
        ):
            return None
        q = parse_qs(p.query, strict_parsing=True)
        if set(q) != {"PRJID", "LOCID", "LAYOUT", "RESOLUTION", "IMAGETYPE"}:
            return None
        if any(len(v) != 1 for v in q.values()):
            return None
        if (
            not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", q["PRJID"][0])
            or not re.fullmatch(r"[0-9]{1,12}", q["LOCID"][0])
            or q["LAYOUT"][0] not in ("1", "5")
            or q["RESOLUTION"][0] not in ("2500", "3000")
            or q["IMAGETYPE"][0] != "JPG"
        ):
            return None
        return value
    except ValueError:
        return None


def number(value):
    try:
        if isinstance(value, bool):
            return None
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError, OverflowError):
        return None


def query_berlin(bounds, native_bounds, cancel=lambda: False):
    if not supports_berlin(bounds):
        raise ValueError("Choose a small area in the Berlin region.")
    if (
        len(native_bounds) != 4
        or not all(math.isfinite(v) for v in native_bounds)
        or native_bounds[0] >= native_bounds[2]
        or native_bounds[1] >= native_bounds[3]
    ):
        raise ValueError("Invalid projected Berlin query area.")
    if cancel():
        raise InterruptedError("Search cancelled.")
    params = dict(
        service="WFS",
        version="2.0.0",
        request="GetFeature",
        typeNames="bohrdaten:bohrpunkte",
        count=LIMIT,
        srsName="urn:ogc:def:crs:OGC:1.3:CRS84",
        bbox=",".join(map(str, native_bounds)) + ",EPSG:25833",
        outputFormat="application/json",
    )
    url = BERLIN + "?" + urlencode(params)
    data = request(url, timeout=30)
    if cancel():
        raise InterruptedError("Search cancelled.")
    if (
        data.get("type") != "FeatureCollection"
        or data.get("crs", {}).get("properties", {}).get("name") != "urn:ogc:def:crs:CRS::84"
        or not isinstance(data.get("features"), list)
    ):
        raise ValueError("Berlin service returned unexpected data or CRS. Coverage unknown.")
    rows = data["features"]
    result, seen, invalid = [], set(), 0
    retrieved = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for row in rows[:LIMIT]:
        g, p = row.get("geometry") or {}, row.get("properties") or {}
        xy = g.get("coordinates")
        ident = p.get("schluessel")
        if (
            g.get("type") != "Point"
            or not isinstance(xy, list)
            or len(xy) != 2
            or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in xy)
            or not bounds[0] <= xy[0] <= bounds[2]
            or not bounds[1] <= xy[1] <= bounds[3]
            or not isinstance(ident, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", ident)
        ):
            invalid += 1
            continue
        if ident in seen:
            continue
        seen.add(ident)
        depth = number(p.get("endteufe"))
        url_profile = profile_url(p.get("profil"))
        result.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": xy},
                "properties": {
                    "borehole_id": ident,
                    "reported_length_m": depth if depth is not None and depth >= 0 else None,
                    "reported_collar_m": number(p.get("ansatzhoehe")),
                    "vertical_datum": None,
                    "profile_url": url_profile,
                    "survey": "Berlin geological database",
                    "source": BERLIN,
                    "attribution": CREDIT,
                    "terms": TERMS,
                    "retrieved_utc": retrieved,
                    "record_type": (
                        "profile_document_link" if url_profile else "location_and_header"
                    ),
                    "intervals_available": None,
                    "drilling_date": (
                        p.get("bohrbeginn") if isinstance(p.get("bohrbeginn"), str) else None
                    ),
                },
            }
        )
    matched = data.get("numberMatched")
    return {
        "type": "FeatureCollection",
        "features": result,
        "groundsurf": {
            "source": BERLIN,
            "attribution": CREDIT,
            "terms": TERMS,
            "licence": "dl-de-zero-2.0 (WFS metadata)",
            "retrieved_utc": retrieved,
            "query_url": url,
            "query_bounds_wgs84": list(bounds),
            "limit_reached": len(rows) >= LIMIT
            or (isinstance(matched, int) and matched > len(rows)),
            "invalid_records": invalid,
            "limitations": (
                "Regional coverage only; profile links not verified individually; "
                "no structured intervals; collar vertical datum unverified."
            ),
        },
    }
