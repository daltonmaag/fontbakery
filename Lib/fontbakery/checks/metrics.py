import os
from fontTools.pens.boundsPen import BoundsPen
from fontbakery.prelude import check, condition, Message, PASS, FAIL, WARN, SKIP
from fontbakery.testable import CheckRunContext


@condition(CheckRunContext)
def vmetrics(collection):
    from fontbakery.utils import get_bounding_box

    v_metrics = {"ymin": 0, "ymax": 0}
    for ttFont in collection.ttFonts:
        font_ymin, font_ymax = get_bounding_box(ttFont)
        v_metrics["ymin"] = min(font_ymin, v_metrics["ymin"])
        v_metrics["ymax"] = max(font_ymax, v_metrics["ymax"])
    return v_metrics


@check(
    id="family/win_ascent_and_descent",
    conditions=["vmetrics", "not is_cjk_font"],
    rationale="""
        A font's winAscent and winDescent values should be greater than or equal to
        the head table's yMax, abs(yMin) values. If they are less than these values,
        clipping can occur on Windows platforms
        (https://github.com/RedHatBrand/Overpass/issues/33).

        If the font includes tall/deep writing systems such as Arabic or Devanagari,
        the winAscent and winDescent can be greater than the yMax and absolute yMin
        values to accommodate vowel marks.

        When the 'win' Metrics are significantly greater than the UPM, the linespacing
        can appear too loose. To counteract this, enabling the OS/2 fsSelection
        bit 7 (Use_Typo_Metrics), will force Windows to use the OS/2 'typo' values
        instead. This means the font developer can control the linespacing with
        the 'typo' values, whilst avoiding clipping by setting the 'win' values to
        values greater than the yMax and absolute yMin.
    """,
    proposal="https://github.com/fonttools/fontbakery/issues/4829",  # legacy check
)
def check_family_win_ascent_and_descent(ttFont, vmetrics):
    """Checking OS/2 usWinAscent & usWinDescent."""

    # NOTE:
    # This check works on a single font file as well as on a group of font files.
    # Even though one of this check's inputs is 'ttFont' (whereas other family-wide
    # checks use 'ttFonts') the other input parameter, 'vmetrics', will collect vertical
    # metrics values for all the font files provided in the command line. This means
    # that running the check may yield more or less results depending on the set of font
    # files that is provided in the command line. This behaviour is NOT a bug.
    # For example, compare the results of these two commands:
    #   fontbakery check-universal -c ascent_and_descent data/test/mada/Mada-Regular.ttf
    #   fontbakery check-universal -c ascent_and_descent data/test/mada/*.ttf
    #
    # The second command will yield more FAIL results for each font. This happens
    # because the check does a family-wide validation of the vertical metrics, instead
    # of a single font validation.

    if "OS/2" not in ttFont:
        yield FAIL, Message("lacks-OS/2", "Font file lacks OS/2 table")
        return

    failed = False
    os2_table = ttFont["OS/2"]
    win_ascent = os2_table.usWinAscent
    win_descent = os2_table.usWinDescent
    y_max = vmetrics["ymax"]
    y_min = vmetrics["ymin"]

    # OS/2 usWinAscent:
    if win_ascent < y_max:
        failed = True
        yield FAIL, Message(
            "ascent",
            f"OS/2.usWinAscent value should be equal or greater than {y_max},"
            f" but got {win_ascent} instead",
        )
    if win_ascent > y_max * 2:
        failed = True
        yield FAIL, Message(
            "ascent",
            f"OS/2.usWinAscent value {win_ascent} is too large."
            f" It should be less than double the yMax. Current yMax value is {y_max}",
        )
    # OS/2 usWinDescent:
    if win_descent < abs(y_min):
        failed = True
        yield FAIL, Message(
            "descent",
            f"OS/2.usWinDescent value should be equal or greater than {abs(y_min)},"
            f" but got {win_descent} instead",
        )

    if win_descent > abs(y_min) * 2:
        failed = True
        yield FAIL, Message(
            "descent",
            f"OS/2.usWinDescent value {win_descent} is too large."
            " It should be less than double the yMin."
            f" Current absolute yMin value is {abs(y_min)}",
        )
    if not failed:
        yield PASS, "OS/2 usWinAscent & usWinDescent values look good!"


@check(
    id="os2_metrics_match_hhea",
    conditions=["not is_cjk_font"],
    rationale="""
        OS/2 and hhea vertical metric values should match. This will produce the
        same linespacing on Mac, GNU+Linux and Windows.

        - Mac OS X uses the hhea values.
        - Windows uses OS/2 or Win, depending on the OS or fsSelection bit value.

        When OS/2 and hhea vertical metrics match, the same linespacing results on
        macOS, GNU+Linux and Windows. Note that fixing this issue in a previously
        released font may cause reflow in user documents and unhappy users.
    """,
    proposal="https://github.com/fonttools/fontbakery/issues/4829",  # legacy check
)
def check_os2_metrics_match_hhea(ttFont):
    """Checking OS/2 Metrics match hhea Metrics."""

    filename = os.path.basename(ttFont.reader.file.name)

    # Check both OS/2 and hhea are present.
    missing_tables = False

    required = ["OS/2", "hhea"]
    for key in required:
        if key not in ttFont:
            missing_tables = True
            yield FAIL, Message(f"lacks-{key}", f"{filename} lacks a '{key}' table.")

    if missing_tables:
        return

    # OS/2 sTypoAscender and sTypoDescender match hhea ascent and descent
    if ttFont["OS/2"].sTypoAscender != ttFont["hhea"].ascent:
        yield FAIL, Message(
            "ascender",
            f"OS/2 sTypoAscender ({ttFont['OS/2'].sTypoAscender})"
            f" and hhea ascent ({ttFont['hhea'].ascent}) must be equal.",
        )
    elif ttFont["OS/2"].sTypoDescender != ttFont["hhea"].descent:
        yield FAIL, Message(
            "descender",
            f"OS/2 sTypoDescender ({ttFont['OS/2'].sTypoDescender})"
            f" and hhea descent ({ttFont['hhea'].descent}) must be equal.",
        )
    elif ttFont["OS/2"].sTypoLineGap != ttFont["hhea"].lineGap:
        yield FAIL, Message(
            "lineGap",
            f"OS/2 sTypoLineGap ({ttFont['OS/2'].sTypoLineGap})"
            f" and hhea lineGap ({ttFont['hhea'].lineGap}) must be equal.",
        )
    else:
        yield PASS, "OS/2.sTypoAscender/Descender values match hhea.ascent/descent."


@check(
    id="family/vertical_metrics",
    rationale="""
        We want all fonts within a family to have the same vertical metrics so
        their line spacing is consistent across the family.
    """,
    proposal="https://github.com/fonttools/fontbakery/issues/1487",
)
def check_family_vertical_metrics(ttFonts):
    """Each font in a family must have the same set of vertical metrics values."""
    failed = []
    vmetrics = {
        "sTypoAscender": {},
        "sTypoDescender": {},
        "sTypoLineGap": {},
        "usWinAscent": {},
        "usWinDescent": {},
        "ascent": {},
        "descent": {},
        "lineGap": {},
    }

    missing_tables = False
    for ttFont in ttFonts:
        filename = os.path.basename(ttFont.reader.file.name)
        if "OS/2" not in ttFont:
            missing_tables = True
            yield FAIL, Message("lacks-OS/2", f"{filename} lacks an 'OS/2' table.")
            continue

        if "hhea" not in ttFont:
            missing_tables = True
            yield FAIL, Message("lacks-hhea", f"{filename} lacks a 'hhea' table.")
            continue

        full_font_name = ttFont["name"].getBestFullName()
        vmetrics["sTypoAscender"][full_font_name] = ttFont["OS/2"].sTypoAscender
        vmetrics["sTypoDescender"][full_font_name] = ttFont["OS/2"].sTypoDescender
        vmetrics["sTypoLineGap"][full_font_name] = ttFont["OS/2"].sTypoLineGap
        vmetrics["usWinAscent"][full_font_name] = ttFont["OS/2"].usWinAscent
        vmetrics["usWinDescent"][full_font_name] = ttFont["OS/2"].usWinDescent
        vmetrics["ascent"][full_font_name] = ttFont["hhea"].ascent
        vmetrics["descent"][full_font_name] = ttFont["hhea"].descent
        vmetrics["lineGap"][full_font_name] = ttFont["hhea"].lineGap

    if not missing_tables:
        # It is important to first ensure all font files have OS/2 and hhea tables
        # before performing the rest of the check routine.

        for k, v in vmetrics.items():
            metric_vals = set(vmetrics[k].values())
            if len(metric_vals) != 1:
                failed.append(k)

        if failed:
            for k in failed:
                s = ["{}: {}".format(k, v) for k, v in vmetrics[k].items()]
                s = "\n".join(s)
                yield FAIL, Message(
                    f"{k}-mismatch", f"{k} is not the same across the family:\n{s}"
                )
        else:
            yield PASS, "Vertical metrics are the same across the family."


@check(
    id="linegaps",
    rationale="""
        The LineGap value is a space added to the line height created by the union
        of the (typo/hhea)Ascender and (typo/hhea)Descender. It is handled differently
        according to the environment.

        This leading value will be added above the text line in most desktop apps.
        It will be shared above and under in web browsers, and ignored in Windows
        if Use_Typo_Metrics is disabled.

        For better linespacing consistency across platforms,
        (typo/hhea)LineGap values must be 0.
    """,
    proposal=[
        "https://github.com/fonttools/fontbakery/issues/4133",
        "https://googlefonts.github.io/gf-guide/metrics.html",
    ],
)
def check_linegaps(ttFont):
    """Checking Vertical Metric Linegaps."""

    required_tables = {"hhea", "OS/2"}
    missing_tables = sorted(required_tables - set(ttFont.keys()))
    if missing_tables:
        for table_tag in missing_tables:
            yield FAIL, Message("lacks-table", f"Font lacks '{table_tag}' table.")
        return

    if ttFont["hhea"].lineGap != 0:
        yield WARN, Message("hhea", "hhea lineGap is not equal to 0.")
    elif ttFont["OS/2"].sTypoLineGap != 0:
        yield WARN, Message("OS/2", "OS/2 sTypoLineGap is not equal to 0.")
    else:
        yield PASS, "OS/2 sTypoLineGap and hhea lineGap are both 0."


@check(
    id="typoascender_exceeds_Agrave",
    rationale="""
        MacOS uses OS/2.sTypoAscender/Descender values to determine the line height
        of a font. If the sTypoAscender value is smaller than the maximum height of
        the uppercase /Agrave, the font’s sTypoAscender value is ignored, and a very
        tall line height is used instead.

        This happens on a per-font, per-style basis, so it’s possible for a font to
        have a good sTypoAscender value in one style but not in another. This can
        lead to inconsistent line heights across a typeface family.

        So, it is important to ensure that the sTypoAscender value is greater than
        the maximum height of the uppercase /Agrave in all styles of a type family.
    """,
    proposal="https://github.com/fonttools/fontbakery/issues/3170",
)
def check_typoascender_exceeds_Agrave(ttFont):
    """Checking that the typoAscender exceeds the yMax of the /Agrave."""

    # This check modifies the font file with `.draw(pen)`
    # so here we'll work with a copy of the object so that we
    # do not affect other checks:
    from copy import deepcopy

    ttFont_copy = deepcopy(ttFont)

    if "OS/2" not in ttFont_copy:
        yield FAIL, Message("lacks-OS/2", "Font file lacks OS/2 table")
        return

    glyphset = ttFont_copy.getGlyphSet()

    if "Agrave" not in glyphset and "uni00C0" not in glyphset:
        yield SKIP, Message(
            "lacks-Agrave",
            "Font file lacks the /Agrave, so it can’t be compared with typoAscender",
        )
        return

    pen = BoundsPen(glyphset)

    try:
        glyphset["Agrave"].draw(pen)
    except KeyError:
        glyphset["uni00C0"].draw(pen)

    yMax = pen.bounds[-1]

    typoAscender = ttFont_copy["OS/2"].sTypoAscender

    if typoAscender < yMax:
        yield WARN, Message(
            "typoAscender",
            f"OS/2.sTypoAscender value should be greater than {yMax},"
            f" but got {typoAscender} instead",
        )
    else:
        yield PASS, "OS/2.sTypoAscender value is greater than the yMax of /Agrave."


@check(
    id="caps_vertically_centered",
    rationale="""
        This check suggests one possible approach to designing vertical metrics,
        but can be ingnored if you follow a different approach.
        In order to center text in buttons, lists, and grid systems
        with minimal additional CSS work, the uppercase glyphs should be
        vertically centered in the em box.
        This check mainly applies to Latin, Greek, Cyrillic, and other similar scripts.
        For non-latin scripts like Arabic, this check might not be applicable.
        There is a detailed description of this subject at:
        https://x.com/romanshamin_en/status/1562801657691672576
    """,
    proposal="https://github.com/fonttools/fontbakery/issues/4139",
)
def check_caps_vertically_centered(ttFont):
    """Check if uppercase glyphs are vertically centered."""

    from copy import deepcopy

    ttFont_copy = deepcopy(ttFont)

    SOME_UPPERCASE_GLYPHS = ["A", "B", "C", "D", "E", "H", "I", "M", "O", "S", "T", "X"]
    glyphSet = ttFont_copy.getGlyphSet()

    for glyphname in SOME_UPPERCASE_GLYPHS:
        if glyphname not in glyphSet.keys():
            yield SKIP, Message(
                "lacks-ascii",
                "The implementation of this check relies on a few samples"
                " of uppercase latin characters that are not available in this font.",
            )
            return

    highest_point_list = []
    lowest_point_list = []
    for glyphName in SOME_UPPERCASE_GLYPHS:
        pen = BoundsPen(glyphSet)
        glyphSet[glyphName].draw(pen)
        _, lowest_point, _, highest_point = pen.bounds
        highest_point_list.append(highest_point)
        lowest_point_list.append(lowest_point)

    upm = ttFont_copy["head"].unitsPerEm
    line_spacing_factor = 1.20
    error_margin = (line_spacing_factor * upm) * 0.18
    average_cap_height = sum(highest_point_list) / len(highest_point_list)
    average_descender = sum(lowest_point_list) / len(lowest_point_list)

    top_margin = ttFont["hhea"].ascent - average_cap_height
    bottom_margin = abs(ttFont["hhea"].descent) + average_descender

    difference = abs(top_margin - bottom_margin)

    if difference > error_margin:
        yield WARN, Message(
            "vertical-metrics-not-centered",
            "Uppercase glyphs are not vertically centered in the em box.",
        )
    else:
        yield PASS, "Uppercase glyphs are vertically centered in the em box."
