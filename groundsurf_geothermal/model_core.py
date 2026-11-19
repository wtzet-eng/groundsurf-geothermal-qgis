"""Small, self-contained 3D *preliminary* geological modelling kernel.

A positive-weight inverse-distance interpolator honours the supplied contact
elevations at input wells. A planar Delaunay mesh is subdivided, then sampled
for terrain and shared contacts. Adjacent horizons define triangular wedges.
This is not a validated reservoir model, structural model or flow simulator.
"""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import json
import math
import re
from html import escape as escape_xml_attribute

METHOD = "IDW horizon elevation (power=2) on subdivided Delaunay triangulation"
MIN_SEPARATION_M = 0.1
MAX_WELLS = 150
MAX_EXTENT_M = 50000
MAX_SUBDIV = 22
MIN_THICKNESS_M = 0.001


def _finite(raw, label):
    try:
        x = float(raw)
    except (TypeError, ValueError):
        raise ValueError(label + " must be numeric") from None
    if not math.isfinite(x):
        raise ValueError(label + " must be finite")
    return x


def _area(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def _triangle(a,b,c,xy):
    det = _area(xy[a],xy[b],xy[c])
    if abs(det) < 1e-8:
        return None
    return (a,b,c) if det > 0 else (a,c,b)


def _inside_circle(p, a, b, c):
    # Compute circumcentre from local differences to avoid cancellation in UTM.
    ax, ay = a
    bx, by = b
    cx, cy = c
    dx, dy = bx-ax, by-ay
    ex, ey = cx-ax, cy-ay
    denom = 2 * (dx*ey-dy*ex)
    if abs(denom) < 1e-12:
        return False
    d = dx*dx+dy*dy
    e = ex*ex+ey*ey
    ux = (d*ey-e*dy)/denom
    uy = (e*dx-d*ex)/denom
    center_x, center_y = ax+ux,ay+uy
    r2 = ux*ux+uy*uy
    p2 = (p[0]-center_x)**2+(p[1]-center_y)**2
    return p2 <= r2 + max(1e-9, r2*1e-12)


def triangulate(xy):
    """Bowyer–Watson planar Delaunay triangulation; no SciPy dependency."""
    coords = [(_finite(p[0],"x"),_finite(p[1],"y")) for p in xy]
    if not 3 <= len(coords) <= MAX_WELLS:
        raise ValueError(f"Use 3–{MAX_WELLS} wells to build a preliminary model")
    for i, a in enumerate(coords):
        for b in coords[i+1:]:
            if math.dist(a,b) < MIN_SEPARATION_M:
                raise ValueError("Two well locations coincide or are too close")
    if max(x for x,_ in coords)-min(x for x,_ in coords) > MAX_EXTENT_M or (
        max(y for _,y in coords)-min(y for _,y in coords) > MAX_EXTENT_M
    ):
        raise ValueError("Model spans over 50 km; split into smaller UTM models")
    x0, x1 = min(p[0] for p in coords), max(p[0] for p in coords)
    y0, y1 = min(p[1] for p in coords), max(p[1] for p in coords)
    d = max(x1-x0,y1-y0)
    if d < 0.1:
        raise ValueError("All wells occur at almost the same location")
    cx, cy = (x0+x1)/2,(y0+y1)/2
    supertri = [(cx-30*d,cy-30*d), (cx,cy+30*d), (cx+30*d,cy-30*d)]
    all_xy = coords + supertri
    n = len(coords)
    triangles = [_triangle(n,n+1,n+2,all_xy)]
    for idx, p in enumerate(coords):
        bad = [tri for tri in triangles if _inside_circle(
            p, all_xy[tri[0]],all_xy[tri[1]],all_xy[tri[2]]
        )]
        if not bad:
            raise ValueError("Cannot triangulate these well locations")
        boundary = Counter()
        for tri in bad:
            for a,b in ((tri[0],tri[1]),(tri[1],tri[2]),(tri[2],tri[0])):
                boundary[tuple(sorted((a,b)))] += 1
        triangles = [t for t in triangles if t not in bad]
        for (a,b), count in boundary.items():
            if count != 1:
                continue
            tri = _triangle(a,b,idx,all_xy)
            if tri:
                triangles.append(tri)
    output = [tri for tri in triangles if all(k<n for k in tri)]
    if not output:
        raise ValueError("Non-collinear well locations are required")
    return sorted(output)


def idw(x,y, samples, power=2):
    """Exact at wells; all inverse-distance weights positive elsewhere."""
    num=den=0.0
    for sx,sy,value in samples:
        d=math.hypot(x-sx,y-sy)
        if d < 1e-7:
            return value
        weight = d**(-power)
        num += weight*value
        den += weight
    return num/den


def build_mesh(wells, horizon_names, subdivisions=10):
    if not 2 <= len(horizon_names) <= 16:
        raise ValueError("Model requires ground surface and 1–15 contacts")
    subdivisions=int(subdivisions)
    if not 2 <= subdivisions <= MAX_SUBDIV:
        raise ValueError(f"Subdivisions must be 2–{MAX_SUBDIV}")
    xyz = []
    for well in wells:
        x=_finite(well["x"],"projected x")
        y=_finite(well["y"],"projected y")
        values={code:_finite(well["elevations"][code],"elevation "+code)
                for code in horizon_names}
        for upper, lower in zip(horizon_names,horizon_names[1:]):
            if values[upper]-values[lower] < MIN_THICKNESS_M:
                raise ValueError(
                    "Nonpositive unit thickness at well " + str(well["well_id"])
                )
        xyz.append((x,y,values))
    coords = [(x,y) for x,y,_ in xyz]
    triangles = triangulate(coords)
    if len(triangles) * subdivisions * subdivisions > 80000:
        raise ValueError("Model would exceed 80,000 cells; reduce subdivisions")
    samples = {
        code: [(x,y,val[code]) for x,y,val in xyz]
        for code in horizon_names
    }
    vertices=[]
    faces=[]
    lookup={}
    for a,b,c in triangles:
        one,two,three=coords[a],coords[b],coords[c]
        local={}
        for i in range(subdivisions+1):
            for j in range(subdivisions+1-i):
                u=i/subdivisions
                v=j/subdivisions
                w=1-u-v
                x=w*one[0]+u*two[0]+v*three[0]
                y=w*one[1]+u*two[1]+v*three[1]
                key=(round(x,7),round(y,7))
                if key not in lookup:
                    h={code:idw(x,y,samples[code]) for code in horizon_names}
                    for top,bottom in zip(horizon_names,horizon_names[1:]):
                        if h[top] <= h[bottom]:
                            raise ValueError("Interpolated horizons cross; cannot export volume")
                    lookup[key]=len(vertices)
                    vertices.append((x,y,h))
                local[(i,j)]=lookup[key]
        for i in range(subdivisions):
            for j in range(subdivisions-i):
                aa=local[(i,j)]
                bb=local[(i+1,j)]
                cc=local[(i,j+1)]
                if len({aa,bb,cc})==3:
                    faces.append((aa,bb,cc))
                if i+j < subdivisions-1:
                    dd=local[(i+1,j+1)]
                    if len({bb,dd,cc})==3:
                        faces.append((bb,dd,cc))
    if not faces:
        raise ValueError("Triangulation produced no model cells")
    thickness = {
        top: min(h[top]-h[bottom] for _,_,h in vertices)
        for top,bottom in zip(horizon_names,horizon_names[1:])
    }
    return {
        "vertices":vertices,
        "faces":faces,
        "horizons":list(horizon_names),
        "source_triangle_count":len(triangles),
        "min_thickness_by_unit_m":thickness,
        "input_wells":len(wells),
        "subdivisions":subdivisions,
    }


def _flatten(rows):
    return " ".join(str(value) for row in rows for value in row)


def _write_polydata(path, mesh, code):
    vertices, faces = mesh["vertices"], mesh["faces"]
    positions=[(x,y,h[code]) for x,y,h in vertices]
    connectivity=_flatten(faces)
    offsets=" ".join(str(3*(idx+1)) for idx in range(len(faces)))
    # All external data and filenames are escaped or JSON-encoded.
    payload=f'''<?xml version="1.0"?>
<VTKFile type="PolyData" version="0.1" byte_order="LittleEndian">
  <PolyData>
    <Piece NumberOfPoints="{len(vertices)}" NumberOfPolys="{len(faces)}">
      <PointData Scalars="Elevation_m">
        <DataArray type="Float64" Name="Elevation_m" format="ascii">{_flatten([(p[2],) for p in positions])}</DataArray>
      </PointData>
      <Points><DataArray type="Float64" NumberOfComponents="3" format="ascii">{_flatten(positions)}</DataArray></Points>
      <Polys>
        <DataArray type="Int32" Name="connectivity" format="ascii">{connectivity}</DataArray>
        <DataArray type="Int32" Name="offsets" format="ascii">{offsets}</DataArray>
      </Polys>
    </Piece>
  </PolyData>
</VTKFile>
'''
    Path(path).write_text(payload,encoding="utf-8")


def _write_wedges(path, mesh, upper, lower):
    vertices, faces=mesh["vertices"],mesh["faces"]
    n=len(vertices)
    bottom=[(x,y,h[lower]) for x,y,h in vertices]
    top=[(x,y,h[upper]) for x,y,h in vertices]
    triangles=[(a,b,c,a+n,b+n,c+n) for a,b,c in faces]
    offsets=" ".join(str(6*(idx+1)) for idx in range(len(faces)))
    types=" ".join("13" for _ in faces) # VTK_WEDGE=13
    thick=[(sum(vertices[i][2][upper]-vertices[i][2][lower]
                for i in face)/3,) for face in faces]
    payload=f'''<?xml version="1.0"?>
<VTKFile type="UnstructuredGrid" version="0.1" byte_order="LittleEndian">
  <UnstructuredGrid>
    <Piece NumberOfPoints="{2*n}" NumberOfCells="{len(faces)}">
      <CellData Scalars="Thickness_m">
        <DataArray type="Float64" Name="Thickness_m" format="ascii">{_flatten(thick)}</DataArray>
      </CellData>
      <Points><DataArray type="Float64" NumberOfComponents="3" format="ascii">{_flatten(bottom+top)}</DataArray></Points>
      <Cells>
        <DataArray type="Int32" Name="connectivity" format="ascii">{_flatten(triangles)}</DataArray>
        <DataArray type="Int32" Name="offsets" format="ascii">{offsets}</DataArray>
        <DataArray type="UInt8" Name="types" format="ascii">{types}</DataArray>
      </Cells>
    </Piece>
  </UnstructuredGrid>
</VTKFile>
'''
    Path(path).write_text(payload,encoding="utf-8")


def _safe_name(name):
    slug = re.sub(r"[^a-zA-Z0-9_-]+","-",str(name)).strip("-").lower()
    return slug[:48] or "model"


def export_model(mesh, folder, name, epsg, datum, wells, warnings=()):
    """Write a ParaView multiblock scene, triangulated horizons and prism volumes."""
    root=Path(folder)
    root.mkdir(parents=True,exist_ok=True)
    # Never overwrite unrelated files if an output folder already exists.
    if any(root.iterdir()):
        raise ValueError("Choose an empty output directory for a new model")
    outputs=[]
    slugs=[_safe_name(code) for code in mesh["horizons"]]
    if len(set(slugs)) != len(slugs):
        raise ValueError("Two formation codes would use the same output filename")
    try:
        for code in mesh["horizons"]:
            file=f"surface-{_safe_name(code)}.vtp"
            _write_polydata(root/file,mesh,code)
            outputs.append((f"Surface {code}",file))
        for upper,lower in zip(mesh["horizons"],mesh["horizons"][1:]):
            file=f"unit-{_safe_name(upper)}-to-{_safe_name(lower)}.vtu"
            _write_wedges(root/file,mesh,upper,lower)
            outputs.append((f"Unit {upper} to {lower}",file))
        blocks="\n".join(
            f'    <DataSet index="{i}" name="{escape_xml_attribute(label, quote=True)}" '
            f'file="{escape_xml_attribute(file, quote=True)}"/>'
            for i,(label,file) in enumerate(outputs)
        )
        (root/"model.vtm").write_text(
            '<?xml version="1.0"?>\n'
            '<VTKFile type="vtkMultiBlockDataSet" version="1.0" byte_order="LittleEndian">\n'
            '<vtkMultiBlockDataSet>\n'+blocks+'\n'
            '</vtkMultiBlockDataSet>\n</VTKFile>\n',encoding="utf-8")
        manifest={
            "application":"GroundSurf Geothermal", "version":"0.4.5",
            "name":str(name), "created_utc":datetime.now(timezone.utc).isoformat(),
            "method":METHOD, "crs":epsg, "vertical_datum":datum,
            "horizons":mesh["horizons"], "subdivisions":mesh["subdivisions"],
            "triangle_count":len(mesh["faces"]),
            "vertices_count":len(mesh["vertices"]),
            "source_triangle_count":mesh["source_triangle_count"],
            "min_thickness_by_unit_m":mesh["min_thickness_by_unit_m"],
            "input_wells":wells, "warnings":list(warnings),
            "outputs":[{"label":label,"file":file} for label,file in outputs],
            "scene":"model.vtm",
            "limitations":[
                "Preliminary borehole-constrained conceptual interpolation only.",
                "IDW contact elevation is not a validated geostatistical model.",
                "No faults, folds, borehole deviations or geological boundary outside well hull.",
                "Only volumes between shared contacts; deepest unit not extrapolated.",
                "No reservoir, groundwater-flow or thermal transport simulation.",
            ],
        }
        (root/"model.json").write_text(
            json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        return root/"model.vtm", root/"model.json"
    except Exception:
        # Allow inspection of incomplete output, but never register as a model.
        raise
