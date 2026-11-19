"""Metric geometry for well-to-section projection, with no QGIS dependency."""
import math


def _point(p):
    if len(p) != 2:
        raise ValueError("Point requires two coordinates")
    x, y = float(p[0]), float(p[1])
    if not (math.isfinite(x) and math.isfinite(y)):
        raise ValueError("Coordinates must be finite")
    return x, y


def chainage_for_point(point, polyline):
    """Return (distance along, perpendicular offset, total length), metres."""
    points = [_point(p) for p in polyline]
    if len(points) < 2:
        raise ValueError("Section requires at least two vertices")
    x, y = _point(point)
    best = None
    distance_before = 0.0
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        dx, dy = bx-ax, by-ay
        length_sq = dx*dx + dy*dy
        if length_sq < 1e-10:
            raise ValueError("Zero-length segment")
        fraction = max(0., min(1., ((x-ax)*dx+(y-ay)*dy)/length_sq))
        foot_x, foot_y = ax+dx*fraction, ay+dy*fraction
        offset = math.hypot(x-foot_x, y-foot_y)
        along = distance_before + math.sqrt(length_sq)*fraction
        if best is None or offset < best[1]:
            best = (along, offset)
        distance_before += math.sqrt(length_sq)
    return best[0], best[1], distance_before


def auto_line(points):
    """Principal-axis line through >= 2 metric well coordinates.

    This is a *geometry aid*, not a geological structure inference.
    """
    coords = [_point(p) for p in points]
    if len(coords) < 2:
        raise ValueError("Auto-section requires two or more wells")
    mx = sum(x for x, _ in coords) / len(coords)
    my = sum(y for _, y in coords) / len(coords)
    xx = sum((x-mx)**2 for x, y in coords)
    yy = sum((y-my)**2 for x, y in coords)
    xy = sum((x-mx)*(y-my) for x, y in coords)
    if xx+yy < 1:
        raise ValueError("Wells are too close together for automatic section")
    theta = .5 * math.atan2(2*xy, xx-yy)
    ux, uy = math.cos(theta), math.sin(theta)
    scalars = [(x-mx)*ux+(y-my)*uy for x,y in coords]
    lo, hi = min(scalars), max(scalars)
    if hi-lo < 1:
        raise ValueError("Wells are too close together")
    padding = max(25., (hi-lo)*.08)
    start = (mx+(lo-padding)*ux, my+(lo-padding)*uy)
    end = (mx+(hi+padding)*ux, my+(hi+padding)*uy)
    off = [chainage_for_point(p,(start,end))[1] for p in coords]
    buffer_m = max(50., max(off)*1.1 + 10.)
    return [start,end], buffer_m
