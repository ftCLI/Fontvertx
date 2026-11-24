import math

import pathops
from fontTools.pens.recordingPen import RecordingPen

from fontvertx.merge_curves import merge_cubic_segments

K = 4 / 3 * math.tan(math.pi / 16)  # handle length for a 45° arc


def _circle_with_diagonal_nodes(radius: float = 500) -> pathops.Path:
    """A circle made of 8 arcs: nodes at extrema plus nodes at 45°, 135°, ..."""
    path = pathops.Path()
    pen = path.getPen(glyphSet=None)
    pen.moveTo((radius, 0))
    for i in range(8):
        a0, a1 = i * math.pi / 4, (i + 1) * math.pi / 4
        k = K * radius
        c1 = (radius * math.cos(a0) - k * math.sin(a0), radius * math.sin(a0) + k * math.cos(a0))
        c2 = (radius * math.cos(a1) + k * math.sin(a1), radius * math.sin(a1) - k * math.cos(a1))
        pen.curveTo(c1, c2, (radius * math.cos(a1), radius * math.sin(a1)))
    pen.closePath()
    return path


def _ops(path: pathops.Path) -> list[str]:
    pen = RecordingPen()
    path.draw(pen)
    return [op for op, _ in pen.value]


def test_merges_nodes_between_extrema_but_keeps_extrema():
    merged = merge_cubic_segments(_circle_with_diagonal_nodes(), tolerance=1.0)
    ops = _ops(merged)
    assert ops.count("curveTo") == 4
    assert ops[0] == "moveTo" and ops[-1] == "closePath"


def test_zero_tolerance_keeps_everything_that_is_not_exact():
    merged = merge_cubic_segments(_circle_with_diagonal_nodes(), tolerance=0.01)
    assert _ops(merged).count("curveTo") == 8


def test_missing_extrema_are_restored():
    path = pathops.Path()
    pen = path.getPen(glyphSet=None)
    # One cubic spanning a whole half circle: the top extremum has no node
    pen.moveTo((0, 0))
    pen.curveTo((0, 400), (200, 400), (200, 0))
    pen.closePath()
    points = [
        pt for op, args in _recording(merge_cubic_segments(path, tolerance=4.0)) for pt in args
    ]
    assert any(round(y) == 300 for _, y in points)


def _recording(path: pathops.Path) -> list:
    pen = RecordingPen()
    path.draw(pen)
    return pen.value


def test_corners_and_lines_are_preserved():
    path = pathops.Path()
    pen = path.getPen(glyphSet=None)
    pen.moveTo((0, 0))
    pen.lineTo((100, 0))
    pen.curveTo((150, 0), (200, 50), (200, 100))
    pen.curveTo((200, 150), (150, 200), (100, 200))
    pen.lineTo((0, 200))
    pen.closePath()
    before = _ops(path)
    assert _ops(merge_cubic_segments(path, tolerance=1.0)) == before


def test_flat_curves_become_lines():
    path = pathops.Path()
    pen = path.getPen(glyphSet=None)
    pen.moveTo((0, 0))
    pen.curveTo((100, 0.5), (200, -0.5), (300, 0))
    pen.lineTo((300, 200))
    pen.lineTo((0, 200))
    pen.closePath()
    ops = _ops(merge_cubic_segments(path, tolerance=1.0))
    assert "curveTo" not in ops


def test_quadratic_contours_are_elevated_and_merged():
    path = pathops.Path()
    pen = path.getPen(glyphSet=None)
    pen.moveTo((0, 0))
    # A quarter-circle-like arc split in two quadratic segments with a smooth join
    pen.qCurveTo((100, 0), (170, 30), (200, 100))
    pen.qCurveTo((230, 170), (300, 200))
    pen.lineTo((300, 0))
    pen.closePath()
    result = merge_cubic_segments(path, tolerance=4.0)
    assert "qCurveTo" not in _ops(result)


def test_nearly_axis_aligned_handles_are_snapped():
    path = pathops.Path()
    pen = path.getPen(glyphSet=None)
    pen.moveTo((0, 0))
    pen.curveTo((0.4, 100), (50, 200), (100, 200))
    pen.lineTo((100, 0))
    pen.closePath()
    values = [
        pt for op, args in _recording(merge_cubic_segments(path, tolerance=2.0)) for pt in args
    ]
    assert (0.0, 100.0) in values or (0, 100) in values


def test_distant_merge_is_rejected():
    path = pathops.Path()
    pen = path.getPen(glyphSet=None)
    pen.moveTo((0, 0))
    pen.curveTo((0, 100), (100, 200), (200, 200))
    pen.curveTo((300, 200), (400, 100), (400, 0))
    pen.closePath()
    assert _ops(merge_cubic_segments(path, tolerance=0.01)).count("curveTo") >= 2


def test_all_smooth_contour_without_corners_is_unchanged():
    ops = _ops(merge_cubic_segments(_circle_with_diagonal_nodes(), tolerance=0.0))
    assert ops.count("curveTo") == 8
