"""Text and JSON rendering of diagnostics."""
from scribe_lang import diagnostics as d
from scribe_lang.ast import SourceLocation
import json

from scribe_lang.render import render_json, render_text

SOURCE = "x = 1\nprint total\n\tif\tfoo\n"


def loc(line, column, end_line=None, end_column=None):
    return SourceLocation(line=line, column=column, end_line=end_line, end_column=end_column)


def one(code, location, filename="prog.scribe", **args):
    diags = d.Diagnostics(filename)
    diags.error(code, location, **args)
    return diags


def test_error_with_excerpt_and_summary():
    diags = one(d.UNDECLARED_VARIABLE, loc(2, 7, 2, 12), name="total")
    assert render_text(diags, SOURCE) == (
        "prog.scribe:2:7: error[E0201]: use of undeclared variable 'total'\n"
        " 2 | print total\n"
        "   |       ^~~~~\n"
        "1 error generated.\n"
    )


def test_tabs_are_expanded_consistently_in_the_line_and_the_underline():
    diags = one(d.UNDECLARED_VARIABLE, loc(3, 5, 3, 8), name="foo")
    _, line, caret, _ = render_text(diags, SOURCE).splitlines()
    assert "\t" not in line + caret
    assert line.index("foo") == caret.index("^")


def test_single_character_and_zero_width_spans_get_one_caret():
    diags = one(d.UNEXPECTED_CHARACTER, loc(1, 3), char="'='")
    assert render_text(diags, SOURCE).splitlines()[2] == "   |   ^"


def test_span_past_the_end_of_the_line_points_after_it():
    # End-of-file errors point just past the last character.
    diags = one(d.UNEXPECTED_END_OF_FILE, loc(1, 6), expected="'}'")
    assert render_text(diags, SOURCE).splitlines()[2] == "   |      ^"


def test_multi_line_span_is_underlined_to_the_end_of_its_first_line():
    diags = one(d.UNCLOSED_BLOCK, loc(2, 1, 3, 2))
    assert render_text(diags, SOURCE).splitlines()[2] == "   | ^~~~~~~~~~~"


def test_notes_have_their_own_location_and_excerpt():
    diags = d.Diagnostics("prog.scribe")
    diags.error(d.DUPLICATE_LABEL, loc(2, 1, 2, 6), name="print",
                notes=(("first defined here", loc(1, 1, 1, 2)),), help="rename one of them")
    assert render_text(diags, SOURCE) == (
        "prog.scribe:2:1: error[E0302]: duplicate label 'print'\n"
        " 2 | print total\n"
        "   | ^~~~~\n"
        "prog.scribe:1:1: note: first defined here\n"
        " 1 | x = 1\n"
        "   | ^\n"
        "help: rename one of them\n"
        "1 error generated.\n"
    )


def test_note_without_a_location_is_a_plain_line():
    diags = d.Diagnostics("p.scribe")
    diags.error(d.UNDECLARED_LABEL, loc(1, 1), name="x", notes=(("no such label", None),))
    assert "\nnote: no such label\n" in render_text(diags, SOURCE)


def test_diagnostic_without_a_location():
    diags = one(d.CANNOT_READ_SOURCE, None, filename="missing.scribe", path="missing.scribe", reason="No such file")
    assert render_text(diags) == (
        "missing.scribe: error[E0002]: cannot read missing.scribe: No such file\n"
        "1 error generated.\n"
    )


def test_missing_filename_is_shown_as_input():
    diags = one(d.NUMBER_TOO_LARGE, loc(1, 5), filename=None, value="1e99")
    assert render_text(diags).startswith("<input>:1:5: error[E0401]:")


def test_without_source_text_there_is_no_excerpt():
    diags = one(d.UNDECLARED_VARIABLE, loc(2, 7, 2, 12), name="total")
    assert render_text(diags).count("\n") == 2


def test_line_outside_the_source_has_no_excerpt():
    diags = one(d.UNDECLARED_VARIABLE, loc(99, 1), name="x")
    assert " | " not in render_text(diags, SOURCE)


def test_summary_counts_errors_and_warnings():
    warning = d.ErrorCode("W9999", "test-warning", "careful", d.Severity.WARNING)
    diags = d.Diagnostics("p.scribe")
    diags.error(d.UNDECLARED_LABEL, None, name="a")
    diags.error(d.UNDECLARED_LABEL, None, name="b")
    diags.report(warning, loc(1, 1))
    text = render_text(diags, SOURCE)
    assert "p.scribe:1:1: warning[W9999]: careful\n" in text
    assert text.endswith("2 errors and 1 warning generated.\n")


def test_nothing_to_report_renders_nothing():
    assert render_text(d.Diagnostics(), SOURCE) == ""


def test_json_has_every_field():
    diags = d.Diagnostics("prog.scribe")
    diags.error(d.DUPLICATE_LABEL, loc(4, 1, 4, 10), name="top",
                notes=(("first defined here", loc(2, 1, 2, 10)), ("plain", None)), help="rename one")
    assert json.loads(render_json(diags)) == [{
        "code": "E0302",
        "name": "duplicate-label",
        "severity": "error",
        "message": "duplicate label 'top'",
        "span": {"file": "prog.scribe", "line": 4, "column": 1, "end_line": 4, "end_column": 10},
        "notes": [
            {"message": "first defined here",
             "span": {"file": "prog.scribe", "line": 2, "column": 1, "end_line": 2, "end_column": 10}},
            {"message": "plain",
             "span": {"file": "prog.scribe", "line": None, "column": None, "end_line": None, "end_column": None}},
        ],
        "help": "rename one",
    }]


def test_json_of_nothing_is_an_empty_list():
    assert json.loads(render_json(d.Diagnostics())) == []
