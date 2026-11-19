"""Auditable, preliminary 3D model constraints from raw elevation contacts.

This source is completely separate from depth-based well intervals.
It never claims that the top contact is terrain or infers drilled depth.
"""
from collections import defaultdict
from qgis.core import QgsCoordinateTransform, QgsProject

from . import elevation_contacts, model_core, section_geo

INVALID_DATUM = {"", "UNSPECIFIED", "UNKNOWN", "UNVERIFIED", "NONE"}


def gather_contacts(project_path, well_layer):
    """Build metric XYZ samples from verified-common source Z references.

    Wells containing two conflicting Z values for the same geological
    label are excluded rather than silently selecting one of them.
    """
    raw = elevation_contacts.list_contacts(project_path)
    if not raw:
        raise ValueError(
            "No 3D contact elevations found in GroundSurf. "
            "Import a PointZ / X Y Z Strata layer first."
        )
    by_well = defaultdict(list)
    for record in raw:
        by_well[record[0]].append(record)
    candidates, excluded = [], []
    known_wells = {
        str(feature["well_id"]): feature
        for feature in well_layer.getFeatures()
    }
    for well_id, records in sorted(by_well.items()):
        feature = known_wells.get(well_id)
        if feature is None or not feature.hasGeometry():
            excluded.append(f"{well_id}: no matching well location")
            continue
        datum = {r[3] for r in records}
        if len(datum) != 1:
            excluded.append(f"{well_id}: conflicting vertical references")
            continue
        reference = next(iter(datum))
        if reference.upper() in INVALID_DATUM:
            excluded.append(f"{well_id}: unspecified vertical datum")
            continue
        horizons = defaultdict(list)
        for record in records:
            horizons[record[1]].append(record)
        ambiguous = [
            code for code, items in horizons.items()
            if max(r[2] for r in items) - min(r[2] for r in items)
            > model_core.MIN_THICKNESS_M
        ]
        if ambiguous:
            excluded.append(
                f"{well_id}: ambiguous repeated Z for "
                + ", ".join(sorted(ambiguous))
            )
            continue
        location = feature.geometry().asPoint()
        values = {
            code: float(items[0][2]) for code,items in horizons.items()
        }
        candidates.append({
            "well_id": well_id,
            "lon": location.x(), "lat": location.y(),
            "elevations": values, "datum": reference,
            "source": [
                {
                    "formation_code": r[1],
                    "elevation_m": float(r[2]),
                    "source_layer": r[4],
                    "source_crs": r[5],
                    "source_feature_id": r[8],
                }
                for r in records
            ],
        })
    if len(candidates) < 3:
        raise ValueError(
            "Need at least three wells with unambiguous Z contacts and an "
            "explicit common vertical elevation reference. "
            + "; ".join(excluded[:10])
        )
    if len(candidates) > model_core.MAX_WELLS:
        raise ValueError("More than 150 suitable wells; reduce the model area")
    datums = {r["datum"] for r in candidates}
    if len(datums) != 1:
        raise ValueError(
            "More than one vertical elevation datum in contact observations: "
            + ", ".join(sorted(datums))
            + ". Verify and transform elevations before modelling."
        )
    common = set(candidates[0]["elevations"])
    for well in candidates[1:]:
        common &= set(well["elevations"])
    if len(common) < 2:
        raise ValueError(
            "No two shared geological contact horizons among unambiguous wells. "
            "Check unit labels and geological interpretation."
        )
    mean = {
        code: sum(
            w["elevations"][code] for w in candidates
        ) / len(candidates)
        for code in common
    }
    ordered = sorted(common, key=lambda code: (-mean[code], code))
    for well in candidates:
        sequence = [well["elevations"][code] for code in ordered]
        if any(
            upper - lower <= model_core.MIN_THICKNESS_M
            for upper, lower in zip(sequence, sequence[1:])
        ):
            raise ValueError(
                f"Elevation surfaces cross or reverse at {well['well_id']}. "
                "Review raw Z contact labels before 3D modelling."
            )
    metric = section_geo.metric_projection(
        [[w["lon"], w["lat"]] for w in candidates]
    )
    transformer = QgsCoordinateTransform(
        well_layer.crs(), metric, QgsProject.instance()
    )
    samples = []
    provenance = []
    for well in candidates:
        projected = transformer.transform(well["lon"], well["lat"])
        values = {
            code: well["elevations"][code] for code in ordered
        }
        samples.append({
            "well_id": well["well_id"],
            "x": projected.x(), "y": projected.y(),
            "elevations": values,
        })
        provenance.append({
            "well_id": well["well_id"], "longitude": well["lon"],
            "latitude": well["lat"], "vertical_datum": well["datum"],
            "source_type": "raw-Z-elevation-contact",
            "observations": well["source"],
            "modelled_horizons": values,
        })
    warnings = [
        "SOURCE TYPE: original Z contact elevations, NOT depths below ground.",
        "Top geological contact is NOT assumed to be land/ground surface.",
        "Geological unit names are source labels. No structural faults, "
        "geostatistics or interpretation of conflicting units.",
        "User-supplied vertical reference has not been independently surveyed "
        "or verified by GroundSurf.",
        "No interpolation outside the convex hull of the selected wells.",
        "IDW is conceptual. Inspect model.json and source data before use.",
    ]
    all_codes = set().union(
        *(set(w["elevations"]) for w in candidates)
    )
    dropped = all_codes - common
    if dropped:
        warnings.append(
            "Excluded noncommon horizons from every model: "
            + ", ".join(sorted(dropped))
        )
    if excluded:
        warnings.append(
            f"Excluded {len(excluded)} ambiguous/unsuitable wells: "
            + "; ".join(excluded[:20])
        )
    return {
        "samples": samples,
        "horizons": ordered,
        "datum": next(iter(datums)),
        "epsg": metric.authid(),
        "warnings": warnings,
        "provenance": provenance,
        "excluded_well_count": len(excluded),
        "source_type": "Z contacts",
    }
