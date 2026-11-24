import logging

import pathops
from fontTools.cffLib import PrivateDict
from fontTools.misc.psCharStrings import T2CharString
from fontTools.pens.basePen import BasePen
from fontTools.pens.filterPen import DecomposingFilterPen
from fontTools.pens.qu2cuPen import Qu2CuPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.ttLib import TTFont

from fontvertx.contours import simplify_path
from fontvertx.merge_curves import merge_cubic_segments

__all__ = ["quadratics_to_cubics"]

logger = logging.getLogger(__name__)


class _ImpliedOnCurvePen(BasePen):
    """
    Expands TrueType quadratic splines into simple two-point ``qCurveTo`` segments,
    materializing the implied on-curve midpoints. This includes the special case of
    contours with no on-curve points at all (``qCurveTo`` ending with ``None``), which
    ``Qu2CuPen`` cannot handle when ``all_cubic=True``.
    """

    def __init__(self, out_pen) -> None:
        super().__init__(glyphSet=None)
        self._out_pen = out_pen
        self.oncurve_less = False

    def qCurveTo(self, *points) -> None:
        if points and points[-1] is None:
            self.oncurve_less = True
        super().qCurveTo(*points)

    def _moveTo(self, p0) -> None:
        self._out_pen.moveTo(p0)

    def _lineTo(self, p1) -> None:
        self._out_pen.lineTo(p1)

    def _curveToOne(self, p1, p2, p3) -> None:
        self._out_pen.curveTo(p1, p2, p3)

    def _qCurveToOne(self, p1, p2) -> None:
        self._out_pen.qCurveTo(p1, p2)

    def _closePath(self) -> None:
        self._out_pen.closePath()

    def _endPath(self) -> None:
        self._out_pen.endPath()

    def addComponent(self, glyphName, transformation, **kwargs) -> None:
        raise AssertionError("components must be decomposed before this pen")


def _skia_path_from_charstring(charstring: T2CharString) -> pathops.Path:
    path = pathops.Path()
    path_pen = path.getPen(glyphSet=None)
    charstring.draw(path_pen)
    return path


def _charstring_from_skia_path(path: pathops.Path, width: int) -> T2CharString:
    t2_pen = T2CharStringPen(width=width, glyphSet=None)
    path.draw(t2_pen)
    return t2_pen.getCharString()


def quadratics_to_cubics(
    font: TTFont, tolerance: float = 1.0, simplify: int = 0
) -> dict[str, T2CharString]:
    """
    Converts quadratic Bézier splines to cubic curves with a specified tolerance using the
    ``Qu2CuPen``, then removes overlaps and corrects the winding direction of the contours.

    :param font: The TTFont object representing the font to process.
    :type font: TTFont
    :param tolerance: The maximum acceptable deviation in font units when approximating the
        quadratic Bézier curves. Default is 1.0.
    :type tolerance: float
    :param simplify: Merges adjacent smooth cubic segments to reduce the number of
        nodes. The value is the maximum deviation of a merge, as a multiple of ``tolerance``;
        0 (default) disables the simplification.
    :type simplify: int
    :return: A dictionary mapping glyph names to their corresponding T2CharString objects after
        conversion.
    :rtype: dict[str, T2CharString]
    """

    qu2cu_charstrings = {}
    glyph_set = font.getGlyphSet()
    oncurve_less_glyphs = []

    for k, v in glyph_set.items():
        width = v.width

        t2_pen = T2CharStringPen(width=width, glyphSet=None)
        qu2cu_pen = Qu2CuPen(t2_pen, max_err=tolerance, all_cubic=True, reverse_direction=True)
        # Composite glyphs are decomposed upfront (CFF charstrings cannot reference
        # components), and quadratic splines are expanded to simple segments so that
        # oncurve-less contours do not trip Qu2CuPen.
        implied_pen = _ImpliedOnCurvePen(qu2cu_pen)
        pen = DecomposingFilterPen(implied_pen, glyph_set)
        glyph_set[k].draw(pen)
        if implied_pen.oncurve_less:
            oncurve_less_glyphs.append(k)

        charstring = t2_pen.getCharString()
        charstring.private = PrivateDict()
        path = _skia_path_from_charstring(charstring)
        simplified_path = simplify_path(path, glyph_name=k, clockwise=False)
        if simplify > 0:
            simplified_path = merge_cubic_segments(
                simplified_path,
                tolerance=tolerance * simplify,
                min_extremum_distance=tolerance,
            )
        qu2cu_charstrings[k] = _charstring_from_skia_path(path=simplified_path, width=width)

    if oncurve_less_glyphs:
        # These contours had no on-curve points: their midpoints were implied and the
        # conversion is exact, but the outlines are worth a manual check.
        names = ", ".join(oncurve_less_glyphs[:20])
        if len(oncurve_less_glyphs) > 20:
            names += f", … ({len(oncurve_less_glyphs)} total)"
        logger.warning("Glyphs with oncurve-less contours: %s", names)

    return qu2cu_charstrings
