"""QGIS well records -> auditable, preliminary metric 3D model constraints."""
import math
from qgis.core import QgsCoordinateTransform, QgsProject
from . import db, model_core, section_geo


def gather_wells(project_path, well_layer):
    """Enforce common vertical reference, contact order and non-extrapolation."""
    candidate = []
    excluded = []
    feature_list = list(well_layer.getFeatures())
    for feature in feature_list:
        well_id = section_geo._field_text(feature, "well_id")
        ground = section_geo._finite_field(feature, "ground_elev_m")
        depth_total = section_geo._finite_field(feature, "total_depth_m")
        datum = section_geo._field_text(feature, "vertical_datum")
        reason = None
        if not feature.hasGeometry():
            reason = "no location"
        elif ground is None or not datum:
            reason = "ground elevation or vertical datum missing"
        elif depth_total is None or depth_total <= 0:
            reason = "recorded well depth missing"
        contacts = {}
        if reason is None:
            for row in db.intervals(project_path, well_id):
                code, top = row[1], row[2]
                if code and code not in contacts:
                    contacts[code] = {"depth":float(top),"basis":"interval-derived"}
            for row in db.formation_tops(project_path,well_id):
                code = row[1]
                contacts[code] = {"depth":float(row[2]),"basis":row[3]}
            contacts = {k:v for k,v in contacts.items()
                        if 0 < v["depth"] <= depth_total}
            if not contacts:
                reason = "no usable subsurface contact"
        if reason:
            excluded.append(f"{well_id}: {reason}")
            continue
        location = feature.geometry().asPoint()
        candidate.append({
            "well_id":well_id, "lon":location.x(),"lat":location.y(),
            "ground_elev_m":ground,"vertical_datum":datum,
            "total_depth_m":depth_total,"contacts":contacts,
        })
    if len(candidate)<3:
        raise ValueError(
            "At least three spatially separate wells with common elevation datum "
            "and formation contacts are required. " + "; ".join(excluded[:5])
        )
    if len(candidate)>model_core.MAX_WELLS:
        raise ValueError("More than 150 usable wells: please split the model area")
    datums={r["vertical_datum"] for r in candidate}
    if len(datums)!=1:
        raise ValueError(
            "Wells have different vertical datums: " +
            ", ".join(sorted(datums)) +
            ". Transform and validate them before creating a 3D model."
        )
    common=set(candidate[0]["contacts"])
    for r in candidate[1:]:
        common &= set(r["contacts"])
    if not common:
        raise ValueError(
            "No shared subsurface formation contact is present in all included "
            "wells; fill the stratigraphic logs or split the model area."
        )
    # All modelled horizons must be consistently ordered from shallow to deep.
    mean_depth={
        code: sum(r["contacts"][code]["depth"] for r in candidate)/len(candidate)
        for code in common
    }
    ordered=sorted(common,key=lambda code:(mean_depth[code],code))
    for r in candidate:
        depths=[r["contacts"][code]["depth"] for code in ordered]
        if any(b-a <= model_core.MIN_THICKNESS_M for a,b in zip([0]+depths,depths)):
            raise ValueError(
                f"Inconsistent or crossing formation order at {r['well_id']}. "
                "Review logs before interpolating geological volumes."
            )
    # Transform positions only after all geological validation.
    geo_vertices=[[w["lon"],w["lat"]] for w in candidate]
    target_crs=section_geo.metric_projection(geo_vertices)
    converter=QgsCoordinateTransform(well_layer.crs(),target_crs,QgsProject.instance())
    samples=[]
    for w in candidate:
        point=converter.transform(w["lon"],w["lat"])
        values={"ground":w["ground_elev_m"]}
        for code in ordered:
            values[code]=w["ground_elev_m"]-w["contacts"][code]["depth"]
        samples.append({
            "well_id":w["well_id"],"x":point.x(),"y":point.y(),
            "elevations":values,
        })
    warnings=[
        "No interpolation outside the convex hull of included wells.",
        "IDW is a conceptual interpolator, not a validated geological property model.",
        "Only common horizons are modelled. Unlogged wells and noncommon units "
        "cannot constrain these volumes.",
    ]
    if excluded:
        warnings.append(f"Excluded {len(excluded)} wells: " + "; ".join(excluded[:12]))
    datum=next(iter(datums))
    if datum.upper().startswith("DEMO") or "UNDEFINED" in datum.upper():
        warnings.append(
            "WARNING: Synthetic or undefined elevation datum. Results "
            "are not tied to any verified surveying height system."
        )
    provenance=[]
    for w in candidate:
        provenance.append({
            "well_id":w["well_id"],
            "longitude":w["lon"],"latitude":w["lat"],
            "ground_elev_m":w["ground_elev_m"],
            "vertical_datum":datum,
            "contacts":{code:w["contacts"][code] for code in ordered},
        })
    return {
        "samples":samples,
        "horizons":["ground"]+ordered,
        "datum":datum,
        "epsg":target_crs.authid(),
        "warnings":warnings,
        "provenance":provenance,
        "excluded_well_count":len(excluded),
    }
