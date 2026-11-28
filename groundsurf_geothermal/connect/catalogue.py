"""Provider catalogue and reviewed acquisition adapters."""

import math
from pathlib import Path
from urllib.request import HTTPRedirectHandler, build_opener

from .raster import check

BVV = "Bayerische Vermessungsverwaltung · CC BY 4.0"
BAVARIA = "https://geodaten.bayern.de/opengeodata/"
POLAND = "https://www.gov.pl/web/gugik-en/data"
BASE = "https://download1.bayernwolke.de/a/"


def discover(wgs):
    def intersects(b):
        return wgs[0] < b[2] and wgs[2] > b[0] and wgs[1] < b[3] and wgs[3] > b[1]

    result = []
    if intersects((8.96, 47.26, 13.85, 50.57)):
        for role, name, spacing in [
            ("DTM", "Bavaria DGM1", 1),
            ("imagery", "Bavaria DOP40 RGB", 0.4),
        ]:
            result.append(
                dict(
                    name=name,
                    provider="bavaria",
                    providerName="Bavarian survey",
                    role=role,
                    resolutionM=spacing,
                    source=BAVARIA,
                    rights=BVV,
                    access="tile",
                    costEUR=0,
                    acquisitionDate=None,
                    reason=(
                        "Official bare-earth laser survey"
                        if role == "DTM"
                        else "Official orthorectified aerial RGB"
                    ),
                    limitation="Regional bounds are approximate. Tile coverage and survey dates vary.",
                )
            )
    if intersects((14.12, 49.0, 24.15, 54.85)):
        for role, name in [("DTM", "GUGiK NMT"), ("imagery", "GUGiK ORTO")]:
            result.append(
                dict(
                    name=name,
                    provider="poland",
                    providerName="Polish national survey (GUGiK)",
                    role=role,
                    source=POLAND,
                    costEUR=0,
                    access="manual",
                    rights="GUGiK open data; retain sheet metadata",
                    reason="National survey sheets. Select matching year, resolution and vertical reference.",
                )
            )
    return result


def tile_plan(bounds):
    x, y, X, Y = bounds
    a, b = math.floor(x / 1000), math.floor(y / 1000)
    A, B = math.ceil(X / 1000), math.ceil(Y / 1000)
    if (A - a) * (B - b) > 9 or min(A - a, B - b) < 1:
        raise ValueError("Select up to nine 1 km Bavarian tiles per download.")
    return [
        (f"{i}_{j}", BASE + f"dgm/dgm1/{i}_{j}.tif", BASE + f"dop40/data/32{i}_{j}.tif")
        for i in range(a, A)
        for j in range(b, B)
    ]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def acquire(bounds, folder, cancel=lambda: False, progress=lambda p: None):
    plan = tile_plan(bounds)
    result = [[], []]
    folder = Path(folder)
    for count, (tile, dem, image) in enumerate(plan):
        for i, url in enumerate((dem, image)):
            check(cancel)
            path = folder / f"{'dgm1' if i == 0 else 'dop40'}-{tile}.tif"
            try:
                with build_opener(NoRedirect()).open(url, timeout=25) as response, path.open(
                    "xb"
                ) as out:
                    while True:
                        check(cancel)
                        chunk = response.read(256 * 1024)
                        if not chunk:
                            break
                        if out.tell() + len(chunk) > 32 * 1024 * 1024:
                            raise ValueError("Tile exceeds 32 MiB transfer limit.")
                        out.write(chunk)
            except OSError as exc:
                raise ValueError(
                    f"Official tile unavailable ({tile}). Use local data or a smaller area. {exc}"
                ) from exc
            result[i].append(path)
            progress(100 * (2 * count + i + 1) / (2 * len(plan)))
    return result


class BavarianAdapter:
    """Verified source-specific acquisition details, never UI defaults."""

    crs = "EPSG:25832"
    datum = "DHHN2016 (EPSG:7837)"
    rights = BVV
    licence = "https://creativecommons.org/licenses/by/4.0/"
    name = "Bayerische Vermessungsverwaltung"

    def plan(self, bounds):
        return tile_plan(bounds)

    def review(self, bounds, width, height):
        count = len(self.plan(bounds))
        return (
            f"Request {count} DGM1 and DOP40 tile pair(s) from {self.name}?\n"
            f"The service receives tile locations. About {count*24} MB download, €0.\n"
            f"Clip DGM1 by nearest neighbour and resample RGB on a {width} × {height} grid "
            f"({width*height*12/1000000:.1f} MB before compression). Elevations in {self.datum}. "
            "Survey dates may differ. CC BY 4.0."
        )

    def acquire(self, bounds, folder, cancel, progress):
        return acquire(bounds, folder, cancel, progress)


ADAPTERS = {"bavaria": BavarianAdapter()}


def source_groups(sources):
    groups = {}
    for source in sources:
        groups.setdefault(source["provider"], []).append(source)
    return groups


def acquisition_adapter(sources, provider):
    """Only a reviewed adapter with both required datasets can acquire a pair."""
    candidates = source_groups(sources)
    for key, records in candidates.items():
        if provider not in ("auto", key):
            continue
        if key in ADAPTERS and {r["role"] for r in records if r["access"] == "tile"} >= {
            "DTM",
            "imagery",
        }:
            return key, ADAPTERS[key]
    return None, None


def research_sources(wgs):
    """Search portals only. Their presence never establishes coverage or acquisition rights."""
    portals = [
        ("Copernicus Data Space · Sentinel-2 satellite imagery / STAC",
         "https://documentation.dataspace.copernicus.eu/APIs/STAC.html"),
        ("USGS EarthExplorer · Landsat satellite imagery", "https://earthexplorer.usgs.gov/"),
        ("OpenTopography · elevation surveys and public LiDAR", "https://portal.opentopography.org/datasets"),
    ]
    if wgs[0] < 2 and wgs[2] > -9 and wgs[1] < 61 and wgs[3] > 49:
        portals.append(("British Geological Survey · GeoIndex", "https://www.bgs.ac.uk/map-viewers/geoindex-onshore/"))
    return portals
