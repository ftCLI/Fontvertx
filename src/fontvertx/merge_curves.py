"""Merge adjacent smooth cubic Bézier segments into a single segment, within a tolerance."""

import math

import pathops
from fontTools.misc.bezierTools import splitCubicAtT
from fontTools.pens.recordingPen import RecordingPen

__all__ = ["merge_cubic_segments"]

Point = tuple[float, float]
# ("l", (p,)) for lines, ("c", (c1, c2, p)) for cubic curves
_Segment = tuple[str, tuple[Point, ...]]
_Cubic = tuple[Point, Point, Point]

_SAMPLES_PER_SEGMENT = 16
_POLYLINE_STEPS = 48
_REPARAMETERIZE_ITERATIONS = 5
_MAX_TANGENT_ANGLE = math.radians(3.0)
_AXIS_EPSILON = math.sin(_MAX_TANGENT_ANGLE)
_EXTREMUM_MARGIN = 0.01


def _quadratic_run_to_cubics(start: Point, pts: tuple[Point, ...]) -> list[_Cubic]:
    """Elevate a TrueType-style qCurveTo (off-curve points + end point) to cubics."""
    result: list[_Cubic] = []
    p0 = start
    offs, end = pts[:-1], pts[-1]
    for i, off in enumerate(offs):
        if i < len(offs) - 1:
            nxt = offs[i + 1]
            p2 = ((off[0] + nxt[0]) / 2, (off[1] + nxt[1]) / 2)
        else:
            p2 = end
        c1 = (p0[0] + 2 / 3 * (off[0] - p0[0]), p0[1] + 2 / 3 * (off[1] - p0[1]))
        c2 = (p2[0] + 2 / 3 * (off[0] - p2[0]), p2[1] + 2 / 3 * (off[1] - p2[1]))
        result.append((c1, c2, p2))
        p0 = p2
    return result


def _sub(a: Point, b: Point) -> Point:
    return a[0] - b[0], a[1] - b[1]


def _length(v: Point) -> float:
    return math.hypot(v[0], v[1])


def _unit(v: Point) -> Point | None:
    n = _length(v)
    return None if n < 1e-9 else (v[0] / n, v[1] / n)


def _cubic_at(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    mt = 1 - t
    a, b, c, d = mt**3, 3 * mt * mt * t, 3 * mt * t * t, t**3
    return (
        a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
        a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1],
    )


def _start_tangent(p0: Point, c1: Point, c2: Point, p3: Point) -> Point | None:
    return _unit(_sub(c1, p0)) or _unit(_sub(c2, p0)) or _unit(_sub(p3, p0))


def _end_tangent(p0: Point, c1: Point, c2: Point, p3: Point) -> Point | None:
    """Unit vector at the end point, pointing along the direction of travel."""
    return _unit(_sub(p3, c2)) or _unit(_sub(p3, c1)) or _unit(_sub(p3, p0))


def _within_tolerance(p: Point, polyline: list[Point], guess: int, tolerance: float) -> bool:
    """
    True if ``p`` is within ``tolerance`` of ``polyline``. Segments are visited outwards from
    ``guess`` and the search stops at the first close enough one.
    """
    tol2 = tolerance * tolerance
    px, py = p
    count = len(polyline) - 1
    guess = min(max(guess, 0), count - 1)
    for offset in range(count):
        for index in {guess - offset, guess + offset}:
            if not 0 <= index < count:
                continue
            ax, ay = polyline[index]
            bx, by = polyline[index + 1]
            abx, aby = bx - ax, by - ay
            denom = abx * abx + aby * aby
            t = 0.0
            if denom:
                t = max(0.0, min(1.0, ((px - ax) * abx + (py - ay) * aby) / denom))
            dx, dy = px - (ax + t * abx), py - (ay + t * aby)
            if dx * dx + dy * dy <= tol2:
                return True
    return False


def _is_smooth_non_extremum(a_end_tangent: Point, b_start_tangent: Point) -> bool:
    """True if the join is G1-continuous and its tangent is neither horizontal nor vertical."""
    cross = a_end_tangent[0] * b_start_tangent[1] - a_end_tangent[1] * b_start_tangent[0]
    dot = a_end_tangent[0] * b_start_tangent[0] + a_end_tangent[1] * b_start_tangent[1]
    if dot <= 0 or abs(math.atan2(cross, dot)) > _MAX_TANGENT_ANGLE:
        return False
    return abs(a_end_tangent[0]) > _AXIS_EPSILON and abs(a_end_tangent[1]) > _AXIS_EPSILON


def _fit_handles(
    samples: list[Point],
    params: list[float],
    p0: Point,
    p3: Point,
    t0: Point,
    t1: Point,
) -> tuple[Point, Point] | None:
    """Least squares for the two handle lengths; ``t1`` points from ``p3`` back into the curve."""
    c00 = c01 = c11 = x0 = x1 = 0.0
    for pt, u in zip(samples, params, strict=False):
        mu = 1 - u
        w0, w1, w2, w3 = mu**3, 3 * mu * mu * u, 3 * mu * u * u, u**3
        a_vec = (t0[0] * w1, t0[1] * w1)
        b_vec = (t1[0] * w2, t1[1] * w2)
        c00 += a_vec[0] ** 2 + a_vec[1] ** 2
        c01 += a_vec[0] * b_vec[0] + a_vec[1] * b_vec[1]
        c11 += b_vec[0] ** 2 + b_vec[1] ** 2
        tmp = (
            pt[0] - (w0 + w1) * p0[0] - (w2 + w3) * p3[0],
            pt[1] - (w0 + w1) * p0[1] - (w2 + w3) * p3[1],
        )
        x0 += a_vec[0] * tmp[0] + a_vec[1] * tmp[1]
        x1 += b_vec[0] * tmp[0] + b_vec[1] * tmp[1]

    det = c00 * c11 - c01 * c01
    if abs(det) < 1e-12:
        return None
    alpha = (x0 * c11 - x1 * c01) / det
    beta = (c00 * x1 - c01 * x0) / det
    if alpha <= 0 or beta <= 0:
        return None
    return (
        (p0[0] + alpha * t0[0], p0[1] + alpha * t0[1]),
        (p3[0] + beta * t1[0], p3[1] + beta * t1[1]),
    )


def _newton_step(p0: Point, c1: Point, c2: Point, p3: Point, pt: Point, u: float) -> float:
    """One Newton-Raphson step moving ``u`` towards the closest point of the curve to ``pt``."""
    q = _cubic_at(p0, c1, c2, p3, u)
    mu = 1 - u
    d1 = tuple(
        3 * (mu * mu * (c1[i] - p0[i]) + 2 * mu * u * (c2[i] - c1[i]) + u * u * (p3[i] - c2[i]))
        for i in (0, 1)
    )
    d2 = tuple(
        6 * (mu * (c2[i] - 2 * c1[i] + p0[i]) + u * (p3[i] - 2 * c2[i] + c1[i])) for i in (0, 1)
    )
    diff = (q[0] - pt[0], q[1] - pt[1])
    num = diff[0] * d1[0] + diff[1] * d1[1]
    den = d1[0] ** 2 + d1[1] ** 2 + diff[0] * d2[0] + diff[1] * d2[1]
    if abs(den) < 1e-12:
        return u
    return min(1.0, max(0.0, u - num / den))


def _try_merge(
    p0: Point,
    cubics: list[_Cubic],
    tolerance: float,
) -> _Cubic | None:
    """Fit one cubic to the consecutive cubics ``cubics`` starting at ``p0``."""
    p_end = cubics[-1][2]
    t0 = _start_tangent(p0, *cubics[0])
    t1 = _end_tangent(_cubic_start(p0, cubics, len(cubics) - 1), *cubics[-1])
    if t0 is None or t1 is None:
        return None
    back = (-t1[0], -t1[1])

    samples: list[Point] = []
    start = p0
    for c1, c2, p3 in cubics:
        samples.extend(
            _cubic_at(start, c1, c2, p3, i / _SAMPLES_PER_SEGMENT)
            for i in range(_SAMPLES_PER_SEGMENT)
        )
        start = p3
    samples.append(p_end)
    # Chord-length parameterization of the sampled points
    cumulative = [0.0]
    for s, e in zip(samples, samples[1:], strict=False):
        cumulative.append(cumulative[-1] + _length(_sub(e, s)))
    total = cumulative[-1]
    if total == 0:
        return None
    params = [c / total for c in cumulative]

    fitted: tuple[Point, Point] | None = None
    for _ in range(_REPARAMETERIZE_ITERATIONS):
        fitted = _fit_handles(samples, params, p0, p_end, t0, back)
        if fitted is None:
            return None
        c1, c2 = fitted
        params = [
            _newton_step(p0, c1, c2, p_end, pt, u) for pt, u in zip(samples, params, strict=False)
        ]
    if fitted is None:
        return None

    # Round the control points, as the final outline has integer coordinates
    c1 = (round(fitted[0][0]), round(fitted[0][1]))
    c2 = (round(fitted[1][0]), round(fitted[1][1]))
    polyline = [
        _cubic_at(p0, c1, c2, p_end, i / _POLYLINE_STEPS) for i in range(_POLYLINE_STEPS + 1)
    ]
    last = len(samples) - 1
    for s, u in zip(samples, params, strict=False):
        if not _within_tolerance(s, polyline, round(u * _POLYLINE_STEPS), tolerance):
            return None

    # The merged curve must not stray from the original outline in the opposite direction either
    for i, pt in enumerate(polyline):
        if not _within_tolerance(pt, samples, round(i / _POLYLINE_STEPS * last), tolerance):
            return None
    return c1, c2, p_end


def _cubic_start(p0: Point, cubics: list[_Cubic], index: int) -> Point:
    return p0 if index == 0 else cubics[index - 1][2]


def _as_cubic(start: Point, segment: _Segment) -> _Cubic:
    kind, pts = segment
    if kind == "c":
        return pts  # type: ignore[return-value]
    end = pts[0]
    d = _sub(end, start)
    return (
        (start[0] + d[0] / 3, start[1] + d[1] / 3),
        (start[0] + 2 * d[0] / 3, start[1] + 2 * d[1] / 3),
        end,
    )


def _junction_removable(prev_start: Point, prev: _Cubic, nxt: _Cubic) -> bool:
    end_tangent = _end_tangent(prev_start, *prev)
    start_tangent = _start_tangent(prev[2], *nxt)
    return (
        end_tangent is not None
        and start_tangent is not None
        and _is_smooth_non_extremum(end_tangent, start_tangent)
    )


def _extrema_parameters(p0: Point, c1: Point, c2: Point, p3: Point) -> list[tuple[float, int]]:
    """Parameters in (0, 1) where the tangent is horizontal (axis 1) or vertical (axis 0)."""
    found: list[tuple[float, int]] = []
    for axis in (0, 1):
        a = -p0[axis] + 3 * c1[axis] - 3 * c2[axis] + p3[axis]
        b = 3 * (p0[axis] - 2 * c1[axis] + c2[axis])
        c = 3 * (c1[axis] - p0[axis])
        if abs(a) < 1e-9:
            roots = [-c / (2 * b)] if abs(b) > 1e-9 else []
        else:
            disc = b * b - 3 * a * c
            roots = [] if disc < 0 else [(-b + s * math.sqrt(disc)) / (3 * a) for s in (1, -1)]
        found.extend((t, axis) for t in roots if _EXTREMUM_MARGIN < t < 1 - _EXTREMUM_MARGIN)
    return sorted(found)


def _insert_extrema(start: Point, segments: list[_Segment], min_distance: float) -> list[_Segment]:
    """Split cubics at their horizontal and vertical extrema, unless a node is already there."""
    result: list[_Segment] = []
    current = start
    for kind, pts in segments:
        if kind != "c":
            result.append((kind, pts))
            current = pts[-1]
            continue

        c1, c2, p3 = pts
        found = _extrema_parameters(current, c1, c2, p3)
        ts: list[float] = []
        axes: list[int] = []
        for t, axis in found:
            if ts and abs(t - ts[-1]) < 1e-3:
                continue
            point = _cubic_at(current, c1, c2, p3, t)
            if min(_length(_sub(point, current)), _length(_sub(point, p3))) < min_distance:
                continue
            ts.append(t)
            axes.append(axis)
        if not ts:
            result.append((kind, pts))
            current = p3
            continue

        pieces = [[list(p) for p in piece] for piece in splitCubicAtT(current, c1, c2, p3, *ts)]
        # Round the new nodes and keep their handles on the extremum line
        for i, axis in enumerate(axes):
            node = (round(pieces[i][3][0]), round(pieces[i][3][1]))
            for handle in (pieces[i][2], pieces[i + 1][1]):
                handle[axis] = node[axis]
            # Two separate copies: the pieces must not share a mutable point.
            pieces[i][3] = list(node)
            pieces[i + 1][0] = list(node)
        for piece in pieces:
            result.append(("c", tuple((round(p[0]), round(p[1])) for p in piece[1:])))
        current = p3
    return result


def _merge_contour(
    start: Point, segments: list[_Segment], tolerance: float
) -> tuple[Point, list[_Segment]]:
    segs = list(segments)
    if not segs:
        return start, segs
    if segs[-1][1][-1] != start:
        segs.append(("l", (start,)))

    # Rotate the contour so that it starts at a node that must be kept
    starts = [start] + [s[1][-1] for s in segs[:-1]]
    cubics = [_as_cubic(p, s) for p, s in zip(starts, segs, strict=True)]
    rotation = next(
        (
            j
            for j in range(len(segs))
            if not _junction_removable(starts[j - 1], cubics[j - 1], cubics[j])
        ),
        None,
    )
    if rotation is None:
        return start, list(segments)
    segs = segs[rotation:] + segs[:rotation]
    start = starts[rotation]

    origs: list[list[_Cubic]] = [[c] for c in cubics[rotation:] + cubics[:rotation]]

    changed = True
    while changed:
        changed = False
        current = start
        i = 0
        while i < len(segs):
            merged = False
            for run in (3, 2):
                group = segs[i : i + run]
                if len(group) < run or not any(k == "c" for k, _ in group):
                    continue
                cubic_run: list[_Cubic] = []
                point = current
                for seg in group:
                    cubic_run.append(_as_cubic(point, seg))
                    point = seg[1][-1]
                if not all(
                    _junction_removable(
                        _cubic_start(current, cubic_run, j - 1), cubic_run[j - 1], cubic_run[j]
                    )
                    for j in range(1, run)
                ):
                    continue
                # Fit against the original cubics, so that errors do not accumulate
                originals = [c for part in origs[i : i + run] for c in part]
                result = _try_merge(current, originals, tolerance)
                if result is not None:
                    segs[i : i + run] = [("c", result)]
                    origs[i : i + run] = [originals]
                    merged = changed = True
                    break
            if merged:
                continue
            current = segs[i][1][-1]
            i += 1

    if segs and segs[-1][0] == "l" and segs[-1][1][-1] == start:
        segs.pop()
    return start, segs


def _is_flat(p0: Point, seg: _Cubic, tolerance: float) -> bool:
    """True if both handles lie within ``tolerance`` of the chord and between its ends."""
    c1, c2, p3 = seg
    chord = _sub(p3, p0)
    length = _length(chord)
    if length == 0:
        return False
    for h in (c1, c2):
        v = _sub(h, p0)
        along = (v[0] * chord[0] + v[1] * chord[1]) / length
        across = abs(v[0] * chord[1] - v[1] * chord[0]) / length
        if across > tolerance or along < 0 or along > length:
            return False
    return True


def _flat_curves_to_lines(
    start: Point, segments: list[_Segment], tolerance: float
) -> list[_Segment]:
    result: list[_Segment] = []
    prev = start
    for kind, pts in segments:
        if kind == "c" and _is_flat(prev, _as_cubic(prev, (kind, pts)), tolerance):
            kind, pts = "l", (pts[-1],)
        result.append((kind, pts))
        prev = pts[-1]
    return result


def _snap_axis(node: Point, handle: Point, tolerance: float) -> Point:
    dx, dy = handle[0] - node[0], handle[1] - node[1]
    dist = math.hypot(dx, dy)
    if dist == 0:
        return handle
    if 0 < abs(dx) <= tolerance and abs(dx) / dist <= _AXIS_EPSILON:
        return node[0], handle[1]
    if 0 < abs(dy) <= tolerance and abs(dy) / dist <= _AXIS_EPSILON:
        return handle[0], node[1]
    return handle


def _snap_extremum_handles(
    start: Point, segments: list[_Segment], tolerance: float
) -> list[_Segment]:
    """Make handles that are almost horizontal/vertical exactly so."""
    result: list[_Segment] = []
    prev = start
    for kind, pts in segments:
        if kind == "c":
            c1, c2, p3 = pts
            pts = (_snap_axis(prev, c1, tolerance), _snap_axis(p3, c2, tolerance), p3)
        result.append((kind, pts))
        prev = pts[-1]
    return result


def merge_cubic_segments(
    path: pathops.Path, tolerance: float, min_extremum_distance: float = 1.0
) -> pathops.Path:
    """
    Merges runs of up to three segments (curves, and non-axis-aligned lines between curves) joined
    by smooth, non-extremum on-curve points into a single cubic, when the result deviates from the
    original outline by no more than ``tolerance`` font units. Extrema and corners are never
    removed, and the contour start point is moved to one of them if necessary. Extrema that lack
    a node are first restored by splitting the curve there.

    Contours containing anything other than lines and cubic curves are copied unchanged.

    :param path: The path to process.
    :type path: pathops.Path
    :param tolerance: The maximum allowed deviation, in font units.
    :type tolerance: float
    :param min_extremum_distance: An extremum is not restored if an existing node is closer than
        this distance, in font units.
    :type min_extremum_distance: float
    :return: A new path.
    :rtype: pathops.Path
    """
    recording = RecordingPen()
    path.draw(recording)

    result = pathops.Path()
    pen = result.getPen(glyphSet=None)

    contour: list[tuple[str, tuple]] = []
    for op, args in recording.value:
        contour.append((op, args))
        if op not in ("closePath", "endPath"):
            continue

        ops = [o for o, _ in contour]
        if (
            ops[0] == "moveTo"
            and all(o in ("lineTo", "curveTo", "qCurveTo") for o in ops[1:-1])
            and all(a[-1] is not None for _, a in contour[1:-1])
        ):
            start = contour[0][1][0]
            segments: list[_Segment] = []
            cur = start
            for o, a in contour[1:-1]:
                if o == "lineTo":
                    segments.append(("l", tuple(a)))
                    cur = a[-1]
                elif o == "curveTo":
                    segments.append(("c", tuple(a)))
                    cur = a[-1]
                else:
                    for c1, c2, p3 in _quadratic_run_to_cubics(cur, a):
                        segments.append(("c", (c1, c2, p3)))
                        cur = p3
            segments = _insert_extrema(start, segments, min_extremum_distance)
            start, segments = _merge_contour(start, segments, tolerance)
            segments = _flat_curves_to_lines(start, segments, tolerance)
            segments = _snap_extremum_handles(start, segments, tolerance)
            contour = [("moveTo", (start,))]
            contour += [("lineTo" if k == "l" else "curveTo", pts) for k, pts in segments]
            contour.append((op, ()))

        for o, a in contour:
            getattr(pen, o)(*a)
        contour = []

    return result
