from collections import defaultdict
import math

from beziers.path import BezierPath

from fontbakery.callable import condition, check
from fontbakery.testable import Font
from fontbakery.status import PASS, WARN
from fontbakery.message import Message
from fontbakery.utils import bullet_list

ALIGNMENT_MISS_EPSILON = 2  # Two point lee-way on alignment misses
SHORT_PATH_EPSILON = 0.006  # <0.6% of total outline length makes a short segment
SHORT_PATH_ABSOLUTE_EPSILON = 3  # 3 units is a small outline
COLINEAR_EPSILON = 0.1  # Radians
JAG_AREA_EPSILON = 0.05  # <5% of total outline area makes a jaggy segment
JAG_ANGLE = 0.25  # Radians
FALSE_POSITIVE_CUTOFF = 100  # More than this and we don't make a report


@condition(Font)
def outlines_dict(font):
    ttFont = font.ttFont
    reversed_cmap = {v: k for k, v in ttFont.getBestCmap().items()}

    def display_name(glyphname):
        if glyphname in reversed_cmap:
            return f"{glyphname} (U+{reversed_cmap[glyphname]:04X})"
        return glyphname

    return {
        (glyphname, display_name(glyphname)): BezierPath.fromFonttoolsGlyph(
            ttFont, glyphname
        )
        for glyphname in ttFont.getGlyphOrder()
    }


def close_but_not_on(yExpected, yTrue, tolerance):
    if yExpected == yTrue:
        return False
    if abs(yExpected - yTrue) <= tolerance:
        return True
    return False


@check(
    id="outline_alignment_miss",
    rationale=f"""
        This check heuristically looks for on-curve points which are close to, but
        do not sit on, significant boundary coordinates. For example, a point which
        has a Y-coordinate of 1 or -1 might be a misplaced baseline point. As well as
        the baseline, here we also check for points near the x-height (but only for
        lowercase Latin letters), cap-height, ascender and descender Y coordinates.

        Not all such misaligned curve points are a mistake, and sometimes the design
        may call for points in locations near the boundaries. As this check is liable
        to generate significant numbers of false positives, it will pass if there are
        more than {FALSE_POSITIVE_CUTOFF} reported misalignments.
    """,
    conditions=["outlines_dict"],
    proposal="https://github.com/fonttools/fontbakery/pull/3088",
)
def check_outline_alignment_miss(ttFont, outlines_dict, config):
    """Are there any misaligned on-curve points?"""

    warnings = []

    alignments = {
        "baseline": 0,
        "ascender": ttFont["OS/2"].sTypoAscender,
        "descender": ttFont["OS/2"].sTypoDescender,
    }

    # The x-height and cap-height checks (which are useful)
    # use the xHeight and CapHeight fields in the OS/2 table.
    # Those fields are available from version 2 onwards.
    # Any modern font will generally be version 4 or higher, but
    # some historical or otherwise esoteric fonts may have an
    # earlier versioned OS/2 table.
    os2version = ttFont["OS/2"].version
    if os2version >= 2:
        alignments["x-height"] = ttFont["OS/2"].sxHeight
        alignments["cap-height"] = ttFont["OS/2"].sCapHeight
    else:
        yield WARN, Message(
            "skip-cap-x-height-alignment",
            "x-height and cap-height checks are skipped"
            f" because OS/2 table version is only {os2version}"
            " and version >= 2 is required for those checks.",
        )

    for glyph, outlines in outlines_dict.items():
        glyphname, display_name = glyph
        for p in outlines:
            for node in p.asNodelist():
                if node.type == "offcurve":
                    continue
                for line, yExpected in alignments.items():
                    # skip x-height check for caps
                    if line == "x-height" and (
                        len(glyphname) > 1 or glyphname[0].isupper()
                    ):
                        continue
                    if close_but_not_on(yExpected, node.y, ALIGNMENT_MISS_EPSILON):
                        warnings.append(
                            f"{display_name}: X={node.x},Y={node.y}"
                            f" (should be at {line} {yExpected}?)"
                        )
        if len(warnings) > FALSE_POSITIVE_CUTOFF:
            # Let's not waste time.
            yield PASS, (
                "So many Y-coordinates of points were close to"
                " boundaries that this was probably by design."
            )
            return

    if warnings:
        formatted_list = bullet_list(config, warnings, bullet="*")
        yield WARN, Message(
            "found-misalignments",
            f"The following glyphs have on-curve points which"
            f" have potentially incorrect y coordinates:\n\n"
            f"{formatted_list}",
        )
    else:
        yield PASS, "Y-coordinates of points fell on appropriate boundaries."


@check(
    id="outline_short_segments",
    rationale=f"""
        This check looks for outline segments which seem particularly short (less
        than {SHORT_PATH_EPSILON:.1%} of the overall path length).

        This check is not run for variable fonts, as they may legitimately have
        short segments. As this check is liable to generate significant numbers
        of false positives, it will pass if there are more than
        {FALSE_POSITIVE_CUTOFF} reported short segments.
    """,
    conditions=["outlines_dict", "not is_variable_font"],
    proposal="https://github.com/fonttools/fontbakery/pull/3088",
)
def check_outline_short_segments(ttFont, outlines_dict, config):
    """Are any segments inordinately short?"""
    warnings = []

    for glyph, outlines in outlines_dict.items():
        glyphname, display_name = glyph
        for p in outlines:
            outline_length = p.length
            segments = p.asSegments()
            if not segments:
                continue
            prev_was_line = len(segments[-1]) == 2
            for seg in p.asSegments():
                if math.isclose(seg.length, 0):  # That's definitely wrong
                    warnings.append(
                        f"{display_name}" f" contains a short segment {seg}"
                    )
                elif (
                    seg.length < SHORT_PATH_ABSOLUTE_EPSILON
                    or seg.length < SHORT_PATH_EPSILON * outline_length
                ) and (prev_was_line or len(seg) > 2):
                    warnings.append(
                        f"{display_name}" f" contains a short segment {seg}"
                    )
                prev_was_line = len(seg) == 2
        if len(warnings) > FALSE_POSITIVE_CUTOFF:
            yield PASS, (
                "So many short segments were found that this was probably by design."
            )
            return

    if warnings:
        formatted_list = bullet_list(config, warnings, bullet="*")
        yield WARN, Message(
            "found-short-segments",
            f"The following glyphs have segments which seem very short:\n\n"
            f"{formatted_list}",
        )
    else:
        yield PASS, "No short segments were found."


@check(
    id="outline_colinear_vectors",
    rationale="""
        This check looks for consecutive line segments which have the same angle. This
        normally happens if an outline point has been added by accident.

        This check is not run for variable fonts, as they may legitimately have
        colinear vectors.
    """,
    conditions=["outlines_dict", "not is_variable_font"],
    proposal="https://github.com/fonttools/fontbakery/pull/3088",
)
def check_outline_colinear_vectors(ttFont, outlines_dict, config):
    """Do any segments have colinear vectors?"""
    warnings = []

    for glyph, outlines in outlines_dict.items():
        glyphname, display_name = glyph
        for p in outlines:
            segments = p.asSegments()
            if not segments:
                continue
            for i in range(0, len(segments)):
                prev = segments[i - 1]
                this = segments[i]
                if len(prev) == 2 and len(this) == 2:
                    if (
                        abs(prev.tangentAtTime(0).angle - this.tangentAtTime(0).angle)
                        < COLINEAR_EPSILON
                    ):
                        warnings.append(f"{display_name}: {prev} -> {this}")
        if len(warnings) > FALSE_POSITIVE_CUTOFF:
            yield PASS, (
                "So many colinear vectors were found"
                " that this was probably by design."
            )
            return

    if warnings:
        formatted_list = bullet_list(config, sorted(set(warnings)), bullet="*")
        yield WARN, Message(
            "found-colinear-vectors",
            f"The following glyphs have colinear vectors:\n\n" f"{formatted_list}",
        )
    else:
        yield PASS, "No colinear vectors found."


@check(
    id="outline_jaggy_segments",
    rationale="""
        This check heuristically detects outline segments which form a particularly
        small angle, indicative of an outline error. This may cause false positives
        in cases such as extreme ink traps, so should be regarded as advisory and
        backed up by manual inspection.
    """,
    conditions=["outlines_dict", "not is_variable_font"],
    proposal="https://github.com/fonttools/fontbakery/issues/3064",
)
def check_outline_jaggy_segments(ttFont, outlines_dict, config):
    """Do outlines contain any jaggy segments?"""
    warnings = []
    reversed_cmap = {v: k for k, v in ttFont.getBestCmap().items()}

    for glyph, outlines in outlines_dict.items():
        glyphname, display_name = glyph
        for p in outlines:
            segments = p.asSegments()
            if not segments:
                continue
            for i in range(0, len(segments)):
                prev = segments[i - 1]
                this = segments[i]
                in_vector = prev.tangentAtTime(1) * -1
                out_vector = this.tangentAtTime(0)
                if not (in_vector.magnitude * out_vector.magnitude):
                    continue
                angle = (in_vector @ out_vector) / (
                    in_vector.magnitude * out_vector.magnitude
                )
                if not (-1 <= angle <= 1):
                    continue
                jag_angle = math.acos(angle)
                if abs(jag_angle) > JAG_ANGLE or jag_angle == 0:
                    continue
                warnings.append(
                    f"{display_name}: {prev}/{this} = {math.degrees(jag_angle)}"
                )

    if warnings:
        formatted_list = bullet_list(config, sorted(warnings), bullet="*")
        yield WARN, Message(
            "found-jaggy-segments",
            f"The following glyphs have jaggy segments:\n\n" f"{formatted_list}",
        )
    else:
        yield PASS, "No jaggy segments found."


@check(
    id="outline_semi_vertical",
    rationale="""
        This check detects line segments which are nearly, but not quite, exactly
        horizontal or vertical. Sometimes such lines are created by design, but often
        they are indicative of a design error.

        This check is disabled for italic styles, which often contain nearly-upright
        lines.
    """,
    conditions=["outlines_dict", "not is_variable_font", "not is_italic"],
    proposal="https://github.com/fonttools/fontbakery/pull/3088",
)
def check_outline_semi_vertical(ttFont, outlines_dict, config):
    """Do outlines contain any semi-vertical or semi-horizontal lines?"""
    warnings = []

    for glyph, outlines in outlines_dict.items():
        glyphname, display_name = glyph
        for p in outlines:
            segments = p.asSegments()
            if not segments:
                continue
            for s in segments:
                if len(s) != 2:
                    continue
                angle = math.degrees((s.end - s.start).angle)
                for yExpected in [-180, -90, 0, 90, 180]:
                    if close_but_not_on(angle, yExpected, 0.5):
                        warnings.append(f"{display_name}: {s}")

    if warnings:
        formatted_list = bullet_list(config, sorted(warnings), bullet="*")
        yield WARN, Message(
            "found-semi-vertical",
            f"The following glyphs have"
            f" semi-vertical/semi-horizontal lines:\n"
            f"\n"
            f"{formatted_list}",
        )
    else:
        yield PASS, "No semi-horizontal/semi-vertical lines found."


@check(
    id="outline_direction",
    rationale="""
        In TrueType fonts, the outermost contour of a glyph should be oriented
        clockwise, while the inner contours should be oriented counter-clockwise.
        Getting the path direction wrong can lead to rendering issues in some
        software.
    """,
    conditions=["outlines_dict", "is_ttf"],
    proposal="https://github.com/fonttools/fontbakery/issues/2056",
)
def check_outline_direction(ttFont, outlines_dict, config):
    """Check the direction of the outermost contour in each glyph"""
    warnings = []

    def bounds_contains(bb1, bb2):
        return (
            bb1.left <= bb2.left
            and bb1.right >= bb2.right
            and bb1.top >= bb2.top
            and bb1.bottom <= bb2.bottom
        )

    for glyph, outlines in outlines_dict.items():
        glyphname, display_name = glyph
        # Find outlines which are not contained within another outline
        outline_bounds = [path.bounds() for path in outlines]
        is_within = defaultdict(list)
        for i, my_bounds in enumerate(outline_bounds):
            if my_bounds.bl is None:
                warnings.append(
                    f"{display_name} has a path with no bounds (probably a single point)"
                )
                continue
            for j in range(0, len(outline_bounds)):
                if i == j:
                    continue
                their_bounds = outline_bounds[j]
                if their_bounds.bl is None:
                    continue  # Already warned
                if bounds_contains(my_bounds, their_bounds):
                    is_within[j].append(i)
        # The outermost paths are those which are not within anything
        for i, path in enumerate(outlines):
            if is_within[i]:
                continue
            if path.direction == 1:
                warnings.append(f"{display_name} has a counter-clockwise outer contour")

    if warnings:
        formatted_list = bullet_list(config, sorted(warnings), bullet="*")
        yield WARN, Message(
            "ccw-outer-contour",
            f"The following glyphs have a counter-clockwise outer contour:\n\n"
            f"{formatted_list}",
        )


@check(
    id="overlapping_path_segments",
    rationale="""
        Some rasterizers encounter difficulties when rendering glyphs with
        overlapping path segments.

        A path segment is a section of a path defined by two on-curve points.
        When two segments share the same coordinates, they are considered
        overlapping.
    """,
    conditions=["outlines_dict", "is_ttf"],
    proposal="https://github.com/google/fonts/issues/7594#issuecomment-2401909084",
)
def check_overlapping_path_segments(ttFont, outlines_dict, config):
    """Check there are no overlapping path segments"""
    failed = []
    for glyph, outlines in outlines_dict.items():
        seen = set()
        for p in outlines:
            for seg in p.asSegments():
                normal = ((seg.start.x, seg.start.y), (seg.end.x, seg.end.y))
                flipped = ((seg.end.x, seg.end.y), (seg.start.x, seg.start.y))
                if normal in seen or flipped in seen:
                    failed.append(
                        f"{glyph[1]}: {seg} has the same coordinates as a previous segment."
                    )
                seen.add(normal)
    if failed:
        yield WARN, Message(
            "overlapping-path-segments",
            f"The following glyphs have overlapping path segments:\n\n"
            f"{bullet_list(config, failed, bullet='*')}",
        )
    else:
        yield PASS, "No overlapping path segments found."
