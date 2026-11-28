"""Build a bounded scientific summary. Never copy a layer name, URI, attribute or metadata string."""

import hashlib
import math
import re

from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsMapLayerType, QgsProject

from .catalogue import acquisition_adapter, research_sources
from .provider import box
from .raster import grid
from .workflow import TOOLS


def crs_id(crs):
    value = crs.authid()
    return value if re.fullmatch(r"[A-Z0-9_]+:[0-9]+", value or "") else "custom or missing"


def role_hint(layer):
    # Names stay on the device. Only this closed vocabulary crosses the boundary.
    words = set(re.findall(r"\w+", layer.name().casefold()))
    for tags, label in [
        ({"dtm", "dgm1", "nmt"}, "DTM"),
        ({"dsm", "nmpt"}, "DSM"),
        ({"dem"}, "DEM"),
        ({"orthophoto", "ortho", "orto", "dop40", "aerial", "imagery"}, "imagery"),
        ({"geological", "geology", "geologie"}, "geological map"),
    ]:
        if tags & words:
            return label
    return "unknown"


def snapshot(connect):
    project = QgsProject.instance()
    geom, crs, records = connect.area()
    to_wgs = QgsCoordinateTransform(crs, QgsCoordinateReferenceSystem("EPSG:4326"), project)
    extent = box(to_wgs.transformBoundingBox(geom.boundingBox()))
    layers = []
    for layer in project.mapLayers().values():
        raster = layer.type() == QgsMapLayerType.RasterLayer
        item = dict(
            kind=(
                "raster"
                if raster
                else "vector" if layer.type() == QgsMapLayerType.VectorLayer else "other"
            ),
            roleHint=role_hint(layer),
            crs=crs_id(layer.crs()),
            missingCrs=not layer.crs().isValid(),
        )
        if raster and layer.providerType() == "gdal":
            values = [layer.rasterUnitsPerPixelX(), layer.rasterUnitsPerPixelY()]
            if all(math.isfinite(v) and v > 0 for v in values):
                item["pixelSizeInLayerUnits"] = values
        layers.append(item)
    canvas = connect.iface.mapCanvas()
    summary = dict(
        projectCrs=crs_id(project.crs()),
        extentWgs84=[round(v, 6) for v in extent],
        mapExtent=dict(crs=crs_id(canvas.mapSettings().destinationCrs()), bounds=box(canvas.extent())),
        areaMode=connect.mode.currentText(),
        gridSpacingM=connect.spacing.value(),
        layers=layers[:64],
        layerCount=len(layers),
        tools=list(TOOLS),
    )
    provider, adapter = acquisition_adapter(records, connect.source.currentData())
    summary["automaticPair"] = provider
    lines = []
    for record in records:
        info = f"{record['name']} · {record['role']} · {record['access']} · {record.get('rights', 'check rights')}"
        if record.get("resolutionM"):
            info += f" · {record['resolutionM']} m"
        lines.extend([info, record["source"]])
    if adapter:
        target = QgsCoordinateReferenceSystem(adapter.crs)
        from qgis.core import QgsGeometry

        native = QgsGeometry(geom)
        native.transform(QgsCoordinateTransform(crs, target, project))
        bounds = box(native.boundingBox())
        try:
            _, w, h = grid(bounds, connect.spacing.value())
            lines.append(adapter.review(bounds, w, h))
        except ValueError as exc:
            lines.append(str(exc))
            summary["automaticPair"] = None
    else:
        lines.append(
            "Automatic acquisition unavailable for this selection. Prepare locally obtained layers."
        )
    lines.append(
        "Manual searches · verify item coverage, date, resolution, quality, vertical datum, rights and access."
    )
    lines.extend(f"{name}\n{url}" for name, url in research_sources(extent))
    key = (
        project.fileName(),
        tuple(sorted(project.mapLayers())),
        bytes(geom.asWkb()),
        crs.toWkt(),
        connect.spacing.value(),
        connect.source.currentData(),
        repr({k: v for k, v in summary.items() if k != "mapExtent"}),
    )
    return summary, "\n".join(lines), hashlib.sha256(repr(key).encode()).hexdigest()
