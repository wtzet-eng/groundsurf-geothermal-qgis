"""Public QGIS Processing surface. All algorithms run without an AI account."""

import json
import tempfile
from pathlib import Path

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsMapLayerType,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputString,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterCrs,
    QgsProcessingParameterEnum,
    QgsProcessingParameterExtent,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterString,
    QgsProcessingProvider,
)

from .catalogue import discover
from .package import create_package, dump, validate, write_view
from .raster import describe, grid, metric, open_tif, prepare

HELP = {
    "request_landscape": "Review current-map terrain and imagery. Approve the download in QGIS.",
    "inspect_project": "Summarise the project CRS and layer count locally. No credentials or file paths.",
    "inspect_layers": "List layer names, types and horizontal CRS locally. Values are not read.",
    "define_area": "Calculate a metric bounding box and size estimate. A selected polygon can define the mask.",
    "discover_data": "Find official regional candidates using approximate coverage. No download or network request.",
    "prepare_dem": "Clip and warp one confirmed metric elevation raster by nearest neighbour. No vertical conversion.",
    "prepare_imagery": "Warp local 8-bit imagery using the selected RGB bands and bilinear resampling.",
    "align_rasters": "Align RGB imagery to an existing north-up square-pixel metric elevation grid.",
    "validate_coordinates": "Inspect embedded CRS, affine transform, units and NoData. Review vertical datum.",
    "prepare_vectors": "Clip vector features to the extent or selected polygon and reproject into a fresh GeoPackage.",
    "create_transfer_package": "Prepare terrain and RGB on a common metric grid. Creates a new portable folder.",
    "validate_transfer_package": "Check version, paths, checksums, frame and embedded raster grids.",
    "send_to_studio": "Generate an offline preview from a validated transfer folder.",
}
AREA = {
    "define_area",
    "discover_data",
    "prepare_dem",
    "prepare_imagery",
    "prepare_vectors",
    "create_transfer_package",
}
DEM = {"prepare_dem", "align_rasters", "create_transfer_package", "validate_coordinates"}
RGB = {"prepare_imagery", "align_rasters", "create_transfer_package"}
ROLES = ["DTM", "DSM", "DEM"]


def box(r):
    return [r.xMinimum(), r.yMinimum(), r.xMaximum(), r.yMaximum()]


def area_geometry(alg, params, ctx, crs):
    source = alg.parameterAsSource(params, "POLYGON", ctx)
    if source:
        geoms = []
        trans = QgsCoordinateTransform(source.sourceCrs(), crs, ctx.transformContext())
        for feature in source.getFeatures():
            g = QgsGeometry(feature.geometry())
            if g.isEmpty():
                continue
            g.transform(trans)
            geoms.append(g)
            if len(geoms) > 2000:
                raise ValueError("Select up to 2,000 polygons.")
        geom = QgsGeometry.unaryUnion(geoms)
    else:
        rect = alg.parameterAsExtent(params, "AREA", ctx, crs)
        if rect.isEmpty():
            raise ValueError("Select a map extent or polygon.")
        geom = QgsGeometry.fromRect(rect)
    buffer = alg.parameterAsDouble(params, "BUFFER", ctx)
    if buffer:
        geom = geom.buffer(buffer, 12)
    if geom.isEmpty() or not geom.isGeosValid():
        raise ValueError("Area is empty or invalid.")
    return geom


def mask_file(geom, crs, tmp):
    path = Path(tmp) / "area.geojson"
    dump(
        path,
        {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": crs.authid()}},
            "features": [
                {"type": "Feature", "properties": {}, "geometry": json.loads(geom.asJson(12))}
            ],
        },
    )
    return str(path)


class Algorithm(QgsProcessingAlgorithm):
    def __init__(self, key):
        super().__init__()
        self.key = key

    def name(self):
        return self.key

    def displayName(self):
        return self.key.replace("_", " ").capitalize()

    def group(self):
        return "Landscape transfer"

    def groupId(self):
        return "transfer"

    def shortHelpString(self):
        return HELP[self.key]

    def createInstance(self):
        return Algorithm(self.key)

    def flags(self):
        # Project inspection and native child Processing algorithms use main-thread objects.
        return super().flags() | QgsProcessingAlgorithm.FlagNoThreading

    def initAlgorithm(self, config=None):
        k, add = self.key, self.addParameter
        if k == "request_landscape":
            add(
                QgsProcessingParameterBoolean(
                    "OPEN_STUDIO", "Open Studio when the transfer is ready", False
                )
            )
        if k in AREA:
            add(
                QgsProcessingParameterExtent(
                    "AREA", "Area (extent, draw rectangle or layer)", optional=True
                )
            )
            add(
                QgsProcessingParameterFeatureSource(
                    "POLYGON",
                    "Polygon or parcel (overrides extent)",
                    [QgsProcessing.TypeVectorPolygon],
                    optional=True,
                )
            )
            add(QgsProcessingParameterCrs("CRS", "Projected target CRS in metres", "EPSG:25832"))
            add(
                QgsProcessingParameterNumber(
                    "BUFFER", "Buffer (m)", QgsProcessingParameterNumber.Double, 0, minValue=0
                )
            )
        if k in AREA - {"discover_data", "prepare_vectors"}:
            add(
                QgsProcessingParameterNumber(
                    "STEP",
                    "Grid spacing (m)",
                    QgsProcessingParameterNumber.Double,
                    2,
                    minValue=0.01,
                )
            )
        if k in DEM:
            add(
                QgsProcessingParameterRasterLayer(
                    "DEM", "Elevation raster" if k != "validate_coordinates" else "Raster"
                )
            )
        if k in RGB:
            add(QgsProcessingParameterRasterLayer("IMAGE", "Aerial or satellite imagery"))
            add(QgsProcessingParameterString("BANDS", "RGB bands", "1,2,3"))
        if k in ("prepare_dem", "create_transfer_package"):
            add(QgsProcessingParameterEnum("ROLE", "Terrain type", ROLES, defaultValue=2))
            add(
                QgsProcessingParameterBoolean(
                    "METRES", "I verified that elevation values are in metres", False
                )
            )
        if k in ("create_transfer_package", "validate_coordinates"):
            add(
                QgsProcessingParameterString(
                    "DATUM", "Vertical datum (enter unknown if unavailable)", "unknown"
                )
            )
        if k == "create_transfer_package":
            add(
                QgsProcessingParameterString(
                    "RIGHTS", "Source, date if known, attribution and rights for both datasets"
                )
            )
            add(QgsProcessingParameterFolderDestination("OUTPUT", "New transfer directory"))
        if k == "prepare_vectors":
            add(QgsProcessingParameterFeatureSource("VECTOR", "Vector evidence"))
        if k in ("validate_transfer_package", "send_to_studio"):
            add(
                QgsProcessingParameterFile(
                    "PACKAGE", "Transfer directory", QgsProcessingParameterFile.Folder
                )
            )
        formats = {
            "prepare_dem": "GeoTIFF (*.tif)",
            "prepare_imagery": "GeoTIFF (*.tif)",
            "align_rasters": "GeoTIFF (*.tif)",
            "prepare_vectors": "GeoPackage (*.gpkg)",
            "send_to_studio": "Offline preview (*.html)",
        }
        if k in formats:
            add(QgsProcessingParameterFileDestination("OUTPUT", "New output", formats[k]))
        self.addOutput(QgsProcessingOutputString("REPORT", "Result and provenance (JSON)"))

    def processAlgorithm(self, params, ctx, feedback):
        try:
            with tempfile.TemporaryDirectory() as tmp:
                return self.run_tool(params, ctx, feedback, tmp)
        except Exception as exc:
            raise QgsProcessingException(str(exc)) from exc

    def run_tool(self, params, ctx, fb, tmp):
        k = self.key
        project = ctx.project()

        def string(key):
            return self.parameterAsString(params, key, ctx)

        def raster(key):
            layer = self.parameterAsRasterLayer(params, key, ctx)
            if not layer or layer.providerType() != "gdal":
                raise ValueError("Select a local GDAL GeoTIFF layer.")
            return layer.source()

        result = {}
        if k in AREA:
            crs = self.parameterAsCrs(params, "CRS", ctx)
            metric(crs.toWkt())
            if not crs.authid():
                raise ValueError("Choose a registered target CRS.")
            geom = area_geometry(self, params, ctx, crs)
            bounds = box(geom.boundingBox())
            mask = mask_file(geom, crs, tmp)
            target = crs.authid()
            result.update(extent=bounds, crs=target)
        if k in AREA - {"discover_data", "prepare_vectors"}:
            step = self.parameterAsDouble(params, "STEP", ctx)
            _, w, h = grid(bounds, step)
            result.update(dimensions=[w, h], estimatedUncompressedBytes=w * h * 12)
        if k in RGB:
            bands = [int(i.strip()) for i in string("BANDS").split(",")]
        if k in ("prepare_dem", "create_transfer_package"):
            if not self.parameterAsBool(params, "METRES", ctx):
                raise ValueError("Confirm elevation units in metres before preparing terrain.")
            role = ROLES[self.parameterAsEnum(params, "ROLE", ctx)]
        if k == "request_landscape":
            from qgis import utils

            owner = utils.plugins.get("groundsurf_geothermal")
            plugin = getattr(owner, "connect", None)
            if plugin is None or not plugin.registered:
                plugin = utils.plugins.get("groundsurf_connect")
            if plugin is None or utils.iface is None:
                raise ValueError(
                    "This interactive handoff requires the enabled GroundSurf Studio Connector in QGIS Desktop."
                )
            if plugin.task:
                raise ValueError("A landscape transfer is already running.")
            plugin.show()
            if plugin.assistant_dock.running or plugin.assistant_dock.job:
                raise ValueError("An assistant workflow is active.")
            plugin.tabs.setCurrentIndex(1)
            plugin.mode.setCurrentIndex(1)
            plugin.discover()
            plugin.source.setCurrentIndex(0)
            plugin.download_area(self.parameterAsBool(params, "OPEN_STUDIO", ctx))
            result = dict(
                status="queued" if plugin.task else "no download queued",
                destination=plugin.task.destination if plugin.task else None,
            )
        elif k in ("inspect_layers", "inspect_project"):
            if not project:
                raise ValueError("A QGIS project is required.")
            result = dict(crs=project.crs().authid(), layers=len(project.mapLayers()))
            if k == "inspect_layers":
                result["layers"] = [
                    dict(
                        name=layer.name(),
                        crs=layer.crs().authid(),
                        raster=layer.type() == QgsMapLayerType.RasterLayer,
                    )
                    for layer in project.mapLayers().values()
                ]
        elif k == "discover_data":
            trans = QgsCoordinateTransform(
                crs, QgsCoordinateReferenceSystem("EPSG:4326"), ctx.transformContext()
            )
            result["sources"] = discover(box(trans.transformBoundingBox(geom.boundingBox())))
        elif k == "validate_coordinates":
            result = describe(open_tif(raster("DEM")))
            result.update(
                verticalDatum=string("DATUM"),
                warning="Verify vertical reference before comparing elevations.",
            )
        elif k == "validate_transfer_package":
            result = validate(string("PACKAGE"), fb.isCanceled)
        elif k == "send_to_studio":
            write_view(string("PACKAGE"), string("OUTPUT"))
        elif k == "create_transfer_package":
            result = create_package(
                string("OUTPUT"),
                [raster("DEM")],
                [raster("IMAGE")],
                bounds,
                target,
                step,
                role,
                string("DATUM"),
                string("RIGHTS"),
                dict(
                    operation=self.id(),
                    bufferM=self.parameterAsDouble(params, "BUFFER", ctx),
                    area=json.loads(geom.asJson(12)),
                    rgbBands=bands,
                ),
                fb.isCanceled,
                fb.setProgress,
                mask,
                bands,
            )
        elif k in {"prepare_vectors", "prepare_dem", "align_rasters", "prepare_imagery"}:
            dest = Path(string("OUTPUT")).absolute()
            if dest.exists():
                raise ValueError("Choose an unused output filename.")
            with tempfile.TemporaryDirectory(dir=dest.parent) as stage:
                staged = Path(stage) / dest.name
                if k == "prepare_vectors":
                    import processing

                    layer = self.parameterAsSource(params, "VECTOR", ctx)
                    if layer is None:
                        raise ValueError("Select vector evidence.")
                    projected = processing.run(
                        "native:reprojectlayer",
                        {"INPUT": params["VECTOR"], "TARGET_CRS": crs, "OUTPUT": "memory:"},
                        context=ctx,
                        feedback=fb,
                        is_child_algorithm=True,
                    )
                    processing.run(
                        "native:clip",
                        {"INPUT": projected["OUTPUT"], "OVERLAY": mask, "OUTPUT": str(staged)},
                        context=ctx,
                        feedback=fb,
                        is_child_algorithm=True,
                    )
                    result["operation"] = "reproject then polygon clip"
                else:
                    if k == "align_rasters":
                        ds = open_tif(raster("DEM"))
                        x, sx, rx, y, ry, sy = ds.GetGeoTransform()
                        if rx or ry or sx != -sy or sx <= 0:
                            raise ValueError(
                                "Reference grid must be north-up with square metric cells."
                            )
                        bounds = [x, y + sy * ds.RasterYSize, x + sx * ds.RasterXSize, y]
                        target, step, mask = ds.GetProjection(), sx, None
                    elevation = k == "prepare_dem"
                    result = prepare(
                        [raster("DEM" if elevation else "IMAGE")],
                        staged,
                        role if elevation else "imagery",
                        bounds,
                        target,
                        step,
                        fb.isCanceled,
                        fb.setProgress,
                        mask,
                        None if elevation else bands,
                    )
                if fb.isCanceled():
                    raise ValueError("Cancelled")
                staged.rename(dest)
        fb.setProgress(100)
        outputs = {"REPORT": json.dumps(result, ensure_ascii=False)}
        if "OUTPUT" in params:
            outputs["OUTPUT"] = string("OUTPUT")
        return outputs


class Provider(QgsProcessingProvider):
    def id(self):
        return "groundsurf"

    def name(self):
        return "GroundSurf Studio Connector"

    def loadAlgorithms(self):
        for key in HELP:
            self.addAlgorithm(Algorithm(key))
