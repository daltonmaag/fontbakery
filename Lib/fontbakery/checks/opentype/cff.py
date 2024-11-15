from fontbakery.callable import check, condition
from fontbakery.testable import Font, TTCFont
from fontbakery.status import FAIL, WARN
from fontbakery.message import Message


class CFFAnalysis:
    def __init__(self):
        self.glyphs_dotsection = []
        self.glyphs_endchar_seac = []
        self.glyphs_exceed_max = []
        self.glyphs_recursion_errors = []
        self.string_not_ascii = []


def _get_subr_bias(count):
    if count < 1240:
        bias = 107
    elif count < 33900:
        bias = 1131
    else:
        bias = 32768
    return bias


def _traverse_subr_call_tree(info, program, depth):
    global_subrs = info["global_subrs"]
    subrs = info["subrs"]
    gsubr_bias = info["gsubr_bias"]
    subr_bias = info["subr_bias"]

    if depth > info["max_depth"]:
        info["max_depth"] = depth

    # once we exceed the max depth we can stop going deeper
    if depth > 10:
        return

    if (
        len(program) >= 5
        and program[-1] == "endchar"
        and all([isinstance(a, int) for a in program[-5:-1]])
    ):
        info["saw_endchar_seac"] = True
    if "ignore" in program:  # decompiler expresses 'dotsection' as 'ignore'
        info["saw_dotsection"] = True

    while program:
        x = program.pop()
        if x == "callgsubr":
            y = int(program.pop()) + gsubr_bias
            sub_program = global_subrs[y].program.copy()
            _traverse_subr_call_tree(info, sub_program, depth + 1)
        elif x == "callsubr":
            y = int(program.pop()) + subr_bias
            sub_program = subrs[y].program.copy()
            _traverse_subr_call_tree(info, sub_program, depth + 1)


def _analyze_cff(analysis, top_dict, private_dict, fd_index=0):
    char_strings = top_dict.CharStrings
    global_subrs = top_dict.GlobalSubrs
    gsubr_bias = _get_subr_bias(len(global_subrs))

    if hasattr(top_dict, "rawDict"):
        raw_dict = top_dict.rawDict
        for key in ["Notice", "Copyright", "FontName", "FullName", "FamilyName"]:
            for char in raw_dict.get(key, ""):
                if ord(char) > 0x7F:
                    analysis.string_not_ascii.append((key, raw_dict[key]))
                    break

    if private_dict is not None and hasattr(private_dict, "Subrs"):
        subrs = private_dict.Subrs
        subr_bias = _get_subr_bias(len(subrs))
    else:
        subrs = None
        subr_bias = None

    char_list = char_strings.keys()

    for glyph_name in char_list:
        t2_char_string, fd_select_index = char_strings.getItemAndSelector(glyph_name)
        if fd_select_index is not None and fd_select_index != fd_index:
            continue
        try:
            t2_char_string.decompile()
        except RecursionError:
            analysis.glyphs_recursion_errors.append(glyph_name)
            continue
        info = {}
        info["subrs"] = subrs
        info["global_subrs"] = global_subrs
        info["gsubr_bias"] = gsubr_bias
        info["subr_bias"] = subr_bias
        info["max_depth"] = 0
        depth = 0
        program = t2_char_string.program.copy()
        _traverse_subr_call_tree(info, program, depth)
        max_depth = info["max_depth"]

        if max_depth > 10:
            analysis.glyphs_exceed_max.append(glyph_name)
        if info.get("saw_endchar_seac"):
            analysis.glyphs_endchar_seac.append(glyph_name)
        if info.get("saw_dotsection"):
            analysis.glyphs_dotsection.append(glyph_name)


@condition(Font)
def cff_analysis(font):
    from fontTools.ttLib import TTFont

    analysis = CFFAnalysis()
    if isinstance(font, TTCFont):
        ttFont = TTFont(font.file, fontNumber=font.index)
    else:
        ttFont = TTFont(font.file)  # Use our own copy here since we are decompiling

    if "CFF " in ttFont:
        try:
            cff = ttFont["CFF "].cff
        except UnicodeDecodeError:
            analysis.string_not_ascii = None
            return analysis

        for top_dict in cff.topDictIndex:
            if hasattr(top_dict, "FDArray"):
                for fd_index, font_dict in enumerate(top_dict.FDArray):
                    if hasattr(font_dict, "Private"):
                        private_dict = font_dict.Private
                    else:
                        private_dict = None
                    _analyze_cff(analysis, top_dict, private_dict, fd_index)
            else:
                if hasattr(top_dict, "Private"):
                    private_dict = top_dict.Private
                else:
                    private_dict = None
                _analyze_cff(analysis, top_dict, private_dict)

    elif "CFF2" in ttFont:
        cff = ttFont["CFF2"].cff

        for top_dict in cff.topDictIndex:
            for fd_index, font_dict in enumerate(top_dict.FDArray):
                if hasattr(font_dict, "Private"):
                    private_dict = font_dict.Private
                else:
                    private_dict = None
                _analyze_cff(analysis, top_dict, private_dict, fd_index)

    return analysis


@check(
    id="opentype/cff_call_depth",
    conditions=["ttFont", "is_cff"],
    rationale="""
        Per "The Type 2 Charstring Format, Technical Note #5177",
        the "Subr nesting, stack limit" is 10.
    """,
    proposal="https://github.com/fonttools/fontbakery/pull/2425",
)
def check_cff_call_depth(font):
    """Is the CFF subr/gsubr call depth > 10?"""
    analysis = font.cff_analysis

    if analysis.glyphs_exceed_max or analysis.glyphs_recursion_errors:
        for gn in analysis.glyphs_exceed_max:
            yield FAIL, Message(
                "max-depth",
                f'Subroutine call depth exceeded maximum of 10 for glyph "{gn}".',
            )
        for gn in analysis.glyphs_recursion_errors:
            yield FAIL, Message(
                "recursion-error", f'Recursion error while decompiling glyph "{gn}".'
            )


@check(
    id="opentype/cff2_call_depth",
    conditions=["ttFont", "is_cff2"],
    rationale="""
        Per "The CFF2 CharString Format", the "Subr nesting, stack limit" is 10.
    """,
    proposal="https://github.com/fonttools/fontbakery/pull/2425",
)
def check_cff2_call_depth(font):
    """Is the CFF2 subr/gsubr call depth > 10?"""

    analysis = font.cff_analysis

    if analysis.glyphs_exceed_max or analysis.glyphs_recursion_errors:
        for gn in analysis.glyphs_exceed_max:
            yield FAIL, Message(
                "max-depth",
                f'Subroutine call depth exceeded maximum of 10 for glyph "{gn}".',
            )
        for gn in analysis.glyphs_recursion_errors:
            yield FAIL, Message(
                "recursion-error", f'Recursion error while decompiling glyph "{gn}".'
            )


@check(
    id="opentype/cff_deprecated_operators",
    conditions=["ttFont", "is_cff", "cff_analysis"],
    rationale="""
        The 'dotsection' operator and the use of 'endchar' to build accented characters
        from the Adobe Standard Encoding Character Set ("seac") are deprecated in CFF.
        Adobe recommends repairing any fonts that use these, especially endchar-as-seac,
        because a rendering issue was discovered in Microsoft Word with a font that
        makes use of this operation. The check treats that usage as a FAIL.
        There are no known ill effects of using dotsection, so that check is a WARN.
    """,
    proposal="https://github.com/fonttools/fontbakery/pull/3033",
)
def check_cff_deprecated_operators(cff_analysis):
    """Does the font use deprecated CFF operators or operations?"""

    if cff_analysis.glyphs_dotsection or cff_analysis.glyphs_endchar_seac:
        for gn in cff_analysis.glyphs_dotsection:
            yield WARN, Message(
                "deprecated-operator-dotsection",
                f'Glyph "{gn}" uses deprecated "dotsection" operator.',
            )
        for gn in cff_analysis.glyphs_endchar_seac:
            yield FAIL, Message(
                "deprecated-operation-endchar-seac",
                f'Glyph "{gn}" has deprecated use of "endchar"'
                f" operator to build accented characters (seac).",
            )


@check(
    id="opentype/cff_ascii_strings",
    conditions=["ttFont", "is_cff", "cff_analysis"],
    rationale="""
        All CFF Table top dict string chars should fit into the ASCII range.
    """,
    proposal="https://github.com/fonttools/fontbakery/issues/4619",
)
def check_cff_ascii_strings(cff_analysis):
    """Does the font's CFF table top dict strings fit into the ASCII range?"""

    if cff_analysis.string_not_ascii is None:
        yield FAIL, Message(
            "cff-unable-to-decode",
            "Unable to decode CFF table, possibly due to out"
            " of ASCII range strings. Please check table strings.",
        )
    elif cff_analysis.string_not_ascii:
        detailed_info = ""
        for key, string in cff_analysis.string_not_ascii:
            detailed_info += (
                f"\n\n\t - {key}: {string.encode('latin-1').decode('utf-8')}"
            )

        yield FAIL, Message(
            "cff-string-not-in-ascii-range",
            f"The following CFF TopDict strings"
            f" are not in the ASCII range: {detailed_info}",
        )
