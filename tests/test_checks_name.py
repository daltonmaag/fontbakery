from fontTools.ttLib import TTFont

from fontbakery.codetesting import (
    assert_PASS,
    assert_results_contain,
    CheckTester,
    GLYPHSAPP_TEST_FILE,
    TEST_FILE,
)
from fontbakery.constants import NameID
from fontbakery.status import FAIL, WARN


def test_check_name_family_and_style_max_length():
    """Name table entries should not be too long."""
    check = CheckTester("name/family_and_style_max_length")

    # Our reference Cabin Regular is known to be good
    ttFont = TTFont(TEST_FILE("cabinvf/Cabin[wdth,wght].ttf"))

    # So it must PASS the check:
    assert_PASS(check(ttFont), "with a good font...")

    # Then we emit a FAIL with long family/style names
    # See https://github.com/fonttools/fontbakery/issues/2179 for
    # a discussion of the requirements

    for index, name in enumerate(ttFont["name"].names):
        if name.nameID == NameID.FULL_FONT_NAME:
            # This has 33 chars, while the max currently allowed is 32
            bad = "An Absurdly Long Family Name Font"
            assert len(bad) == 33
            ttFont["name"].names[index].string = bad.encode(name.getEncoding())
        if name.nameID == NameID.POSTSCRIPT_NAME:
            bad = "AbsurdlyLongFontName-Regular"
            assert len(bad) == 28
            ttFont["name"].names[index].string = bad.encode(name.getEncoding())

    results = check(ttFont)
    assert_results_contain(results, FAIL, "nameid4-too-long", "with a bad font...")
    assert_results_contain(results, WARN, "nameid6-too-long", "with a bad font...")

    # Restore the original VF
    ttFont = TTFont(TEST_FILE("cabinvf/Cabin[wdth,wght].ttf"))

    # ...and break the check again with a bad fvar instance name:
    nameid_to_break = ttFont["fvar"].instances[0].subfamilyNameID
    for index, name in enumerate(ttFont["name"].names):
        if name.nameID == NameID.FONT_FAMILY_NAME:
            assert len(ttFont["name"].names[index].string) + 28 > 32
        if name.nameID == nameid_to_break:
            bad = "WithAVeryLongAndBadStyleName"
            assert len(bad) == 28
            ttFont["name"].names[index].string = bad.encode(name.getEncoding())
            break
    assert_results_contain(
        check(ttFont), FAIL, "instance-too-long", "with a bad font..."
    )


def DISABLED_test_check_glyphs_file_name_family_and_style_max_length():
    """Combined length of family and style must not exceed 27 characters."""
    check = CheckTester("glyphs_file/name/family_and_style_max_length")

    # Our reference Comfortaa.glyphs is known to be good
    glyphsFile = GLYPHSAPP_TEST_FILE("Comfortaa.glyphs")

    # So it must PASS the check:
    assert_PASS(check(glyphsFile), "with a good font...")

    # Then we emit a WARNing with long family/style names
    # Originaly these were based on the example on the glyphs tutorial
    # (at https://glyphsapp.com/tutorials/multiple-masters-part-3-setting-up-instances)
    # but later we increased a bit the max allowed length.

    # First we expect a WARN with a bad FAMILY NAME
    # This has 28 chars, while the max currently allowed is 27.
    bad = "AnAbsurdlyLongFamilyNameFont"
    assert len(bad) == 28
    glyphsFile.familyName = bad
    assert_results_contain(
        check(glyphsFile), WARN, "too-long", "with a too long font familyname..."
    )

    for i in range(len(glyphsFile.instances)):
        # Restore the good glyphs file...
        glyphsFile = GLYPHSAPP_TEST_FILE("Comfortaa.glyphs")

        # ...and break the check again with a long SUBFAMILY NAME
        # on one of its instances:
        bad_stylename = "WithAVeryLongAndBadStyleName"
        assert len(bad_stylename) == 28
        glyphsFile.instances[i].fullName = f"{glyphsFile.familyName} {bad_stylename}"
        assert_results_contain(
            check(glyphsFile), WARN, "too-long", "with a too long stylename..."
        )