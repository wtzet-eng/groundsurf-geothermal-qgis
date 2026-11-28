"""Small, bounded GDAL operations. Projected metre grids throughout output."""

import math
from pathlib import Path

from osgeo import gdal, osr


def check(cancel):
    if cancel():
        raise ValueError("Cancelled. No finished output was published.")


def open_tif(path):
    path = Path(path)
    if not path.is_file() or path.suffix.lower() not in (".tif", ".tiff"):
        raise ValueError("Select a local, georeferenced GeoTIFF.")
    ds = gdal.OpenEx(
        str(path),
        gdal.OF_RASTER | gdal.OF_READONLY,
        allowed_drivers=["GTiff"],
        sibling_files=[path.name],
    )
    if not ds or not ds.GetSpatialRef() or not ds.GetGeoTransform(can_return_null=True):
        raise ValueError("GeoTIFF needs an embedded CRS and affine transform.")
    return ds


def metric(crs):
    s = osr.SpatialReference()
    if s.SetFromUserInput(crs) != 0 or not s.IsProjected() or abs(s.GetLinearUnits() - 1) > 1e-10:
        raise ValueError("Choose a projected target CRS in metres.")
    return s


def grid(bounds, step):
    if len(bounds) != 4 or not all(math.isfinite(x) for x in (*bounds, step)) or step <= 0:
        raise ValueError("Enter finite bounds and a positive resolution in metres.")
    x, y, X, Y = bounds
    if X <= x or Y <= y:
        raise ValueError("The area is empty.")

    def cells(length):
        ratio = length / step
        rounded = round(ratio)
        return rounded if abs(ratio - rounded) < 1e-8 else math.ceil(ratio)

    w, h = cells(X - x), cells(Y - y)
    if min(w, h) < 2 or w * h > 16000000:
        raise ValueError(
            "Choose an area of at least two rows and columns and at most 16 million cells."
        )
    return [x, Y - h * step, x + w * step, Y], w, h


def describe(ds):
    s = ds.GetSpatialRef()
    band = ds.GetRasterBand(1)
    nodata = band.GetNoDataValue()
    return dict(
        crsWkt=s.ExportToWkt(),
        geoTransform=list(ds.GetGeoTransform()),
        dimensions=[ds.RasterXSize, ds.RasterYSize],
        bands=ds.RasterCount,
        dataType=gdal.GetDataTypeName(band.DataType),
        noData=("NaN" if nodata is not None and math.isnan(nodata) else nodata),
        unit=band.GetUnitType(),
        scale=band.GetScale(),
        offset=band.GetOffset(),
    )


def prepare(
    paths,
    dest,
    role,
    bounds,
    crs,
    step,
    cancel=lambda: False,
    progress=lambda p: None,
    cutline=None,
    bands=None,
):
    """Output path must belong to caller's new staging directory."""
    metric(crs)
    bounds, w, h = grid(bounds, step)
    sources, inputs, refs = [], [], []
    terrain = role in ("DTM", "DSM", "DEM")
    if not terrain and role != "imagery":
        raise ValueError("Unknown raster role.")
    if not paths:
        raise ValueError("Select at least one source GeoTIFF.")
    for path in paths:
        check(cancel)
        ds = open_tif(path)
        band = ds.GetRasterBand(1)
        if terrain:
            if ds.RasterCount != 1 or band.GetColorTable() or band.DataType == gdal.GDT_Byte:
                raise ValueError(
                    "Terrain must be a single numeric elevation band. Byte imagery is unsupported."
                )
            if band.GetScale() not in (None, 1) or band.GetOffset() not in (None, 0):
                raise ValueError("Apply documented elevation scale and offset before import.")
            if band.GetUnitType().lower() not in ("", "m", "meter", "metre", "meters", "metres"):
                raise ValueError("Convert vertical units to metres before transfer.")
            if ds.GetSpatialRef().IsCompound():
                refs.append(
                    ds.GetSpatialRef().GetAttrValue("VERT_CS") or ds.GetSpatialRef().GetName()
                )
        else:
            ids = bands or [1, 2, 3]
            if (
                len(ids) != 3
                or min(ids) < 1
                or max(ids) > ds.RasterCount
                or any(ds.GetRasterBand(i).DataType != gdal.GDT_Byte for i in ids)
            ):
                raise ValueError("Select three 8-bit colour bands for imagery.")
        sources.append(
            dict(
                name=Path(path).name,
                datasetTimestamp=ds.GetMetadataItem("TIFFTAG_DATETIME"),
                bandUnits=band.GetUnitType(),
                **describe(ds),
            )
        )
        if not terrain and (bands or ds.RasterCount not in (3, 4)):
            alpha = [
                i
                for i in range(1, ds.RasterCount + 1)
                if ds.GetRasterBand(i).GetColorInterpretation() == gdal.GCI_AlphaBand
                and i not in ids
            ]
            ds = gdal.Translate("", ds, format="VRT", bandList=ids + alpha[:1])
        inputs.append(ds)
    if len(inputs) > 1 and terrain and (len(set(refs)) > 1 or (refs and len(refs) != len(inputs))):
        raise ValueError("Source vertical references differ.")

    def warp_progress(fraction, message, data):
        progress(fraction * 100)
        return int(not cancel())

    kwargs = dict(
        options=["-novshift"],
        format="GTiff",
        dstSRS=crs,
        outputBounds=bounds,
        width=w,
        height=h,
        cutlineDSName=cutline,
        warpMemoryLimit=64,
        resampleAlg="near" if terrain else "bilinear",
        creationOptions=["TILED=YES", "COMPRESS=DEFLATE", "NUM_THREADS=1"],
        callback=warp_progress,
    )
    if terrain:
        kwargs.update(dstNodata=float("nan"), outputType=gdal.GDT_Float64)
    else:
        kwargs.update(dstAlpha=True, outputType=gdal.GDT_Byte)
    try:
        out = gdal.Warp(str(dest), inputs, **kwargs)
    except RuntimeError as exc:
        check(cancel)
        raise ValueError(f"Raster preparation failed: {exc}") from exc
    check(cancel)
    if out is None:
        raise ValueError("Raster preparation failed: " + gdal.GetLastErrorMsg())
    band = out.GetRasterBand(1)
    if terrain:
        band.SetUnitType("m")
    if not terrain and out.GetRasterBand(out.RasterCount).ComputeRasterMinMax(False)[1] == 0:
        raise ValueError("Imagery does not cover this area.")
    try:
        stats = band.ComputeStatistics(False)
    except RuntimeError as exc:
        raise ValueError(
            f"Could not compute valid raster statistics for the selected area: {exc}"
        ) from exc
    if (
        not stats
        or not all(math.isfinite(v) for v in stats)
        or (band.GetMetadataItem("STATISTICS_VALID_PERCENT") == "0")
    ):
        raise ValueError("No valid raster values in this area.")
    if min(w, h) >= 512:
        out.BuildOverviews("NEAREST" if terrain else "AVERAGE", [2, 4])
    out.FlushCache()
    result = describe(out)
    result.update(
        statistics=stats, sources=sources, resampling="nearest" if terrain else "bilinear"
    )
    return result
