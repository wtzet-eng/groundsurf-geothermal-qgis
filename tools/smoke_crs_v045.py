"""Offscreen QGIS regression: invalid latitude yields actionable CRS diagnostics.

Uses synthetic features only; both ordinary and grouped import paths must
reject the whole batch without writing wells or changing source geometry.
"""
import tempfile
from pathlib import Path

from qgis.core import (
    QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsFeature, QgsField, QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayer,
)
from qgis.PyQt.QtCore import QVariant

from groundsurf_geothermal import qgis_import, grouped_import, storage

app = QgsApplication([], False)
app.initQgis()


def point_layer(crs="EPSG:4326"):
    layer = QgsVectorLayer("Point?crs=" + crs, "Original boreholes", "memory")
    layer.dataProvider().addAttributes([
        QgsField("BH_ID", QVariant.String),
        QgsField("Formation", QVariant.String),
        QgsField("Top", QVariant.Double),
        QgsField("Bottom", QVariant.Double),
    ])
    layer.updateFields()
    return layer


def add_point(layer, x, y, code, formation="SAND", top=0., base=10.):
    feature = QgsFeature(layer.fields())
    feature.setAttributes([code, formation, top, base])
    feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x,y)))
    assert layer.dataProvider().addFeatures([feature])[0]
    layer.updateExtents()


def assert_invalid(layer, selected_only=False):
    well_map={"well_id":"BH_ID"}
    intervals={
        "formation_code":"Formation",
        "top_depth_m":"Top","base_depth_m":"Bottom",
    }
    snapshot = [
        (f.id(),f.geometry().asWkt(),f.attributes())
        for f in layer.getFeatures()
    ]
    for import_path in ("single","grouped"):
        try:
            if import_path == "single":
                qgis_import.prepare_well_records(
                    layer,well_map,selected_only=selected_only
                )
            else:
                grouped_import.prepare_groups(
                    layer,well_map,intervals,selected_only=selected_only
                )
        except ValueError as err:
            message=str(err)
            print(import_path,":",message[:320])
            assert ("latitude" in message.lower()
                    or "longitude" in message.lower()),message
            assert "source geometry X=" in message, message
            assert "EPSG:4326" in message, message
            assert "source LAYER CRS" in message, message
        else:
            raise AssertionError(import_path+" accepted invalid geometry")
    assert snapshot == [
        (f.id(),f.geometry().asWkt(),f.attributes())
        for f in layer.getFeatures()
    ]


with tempfile.TemporaryDirectory() as td:
    gpkg=Path(td)/"wells.gpkg"
    storage.create_project(gpkg)
    target=storage.open_wells(gpkg)

    # Source geometry is clearly projected metres but falsely tagged WGS84.
    layer=point_layer()
    add_point(layer,13.4,52.5,"BH-1")
    add_point(layer,450000,5800000,"BH-2")
    QgsProject.instance().addMapLayer(layer)
    assert_invalid(layer)
    assert target.featureCount()==0

    # Swapped lat/lon symptom when candidate X is plausible latitude.
    swapped=point_layer()
    add_point(swapped,35.2,120.5,"BH-SWAP")
    transform=QgsCoordinateTransform(
        swapped.crs(),QgsCoordinateReferenceSystem("EPSG:4326"),
        QgsProject.instance(),
    )
    feature=next(swapped.getFeatures())
    try:
        qgis_import.checked_wgs84_point(feature,swapped,transform)
    except ValueError as exc:
        assert "X/Y may be reversed" in str(exc)
        print("Swapped coordinates correctly diagnosed.")
    else:
        raise AssertionError("Invalid geographic coordinates accepted")

    # Legitimate projected metres in a correctly declared source CRS work.
    projected=point_layer("EPSG:3857")
    t=QgsCoordinateTransform(
        QgsCoordinateReferenceSystem("EPSG:4326"),projected.crs(),
        QgsProject.instance(),
    )
    point=t.transform(QgsPointXY(13.42,52.51))
    add_point(projected,point.x(),point.y(),"BH-OK")
    record=qgis_import.prepare_well_records(projected,{"well_id":"BH_ID"})[0]
    assert abs(record["latitude"]-52.51)<1e-5,record
    assert abs(record["longitude"]-13.42)<1e-5,record
    print("Valid Web Mercator CRS is transformed normally.")

    # All-or-nothing also holds when the error occurs at source feature 2.
    mapping={"well_id":"BH_ID"}
    for label, prepare in (
        ("single",lambda: qgis_import.prepare_well_records(layer,mapping)),
        ("grouped",lambda: grouped_import.prepare_groups(
            layer,mapping,{
                "formation_code":"Formation",
                "top_depth_m":"Top","base_depth_m":"Bottom",
            }
        )),
    ):
        try:
            prepare()
        except ValueError as exc:
            assert "2" in str(exc),str(exc)
        else:
            raise AssertionError(label+" did not reject invalid feature")

    QgsProject.instance().clear()
    print("PASS v0.4.5: invalid source CRS and swapped latitude diagnosed")
