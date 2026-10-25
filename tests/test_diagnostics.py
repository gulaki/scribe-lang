"""The diagnostic data model, the code registry and the collector."""
import re

import pytest

from scribe_lang import diagnostics as d
from scribe_lang.ast import SourceLocation


def test_codes_are_well_formed_and_unique():
    assert d.CODES, "registry is empty"
    names = [code.name for code in d.CODES.values()]
    assert len(names) == len(set(names))
    for key, code in d.CODES.items():
        assert key == code.code
        assert re.fullmatch(r"[EW]\d{4}", code.code), code.code
        assert re.fullmatch(r"[a-z]+(-[a-z]+)*", code.name), code.name


def test_registering_a_code_twice_is_refused():
    with pytest.raises(ValueError, match="registered twice"):
        d._register("E0201", "something-new", "x")
    with pytest.raises(ValueError, match="registered twice"):
        d._register("E9998", "undeclared-variable", "x")
    assert "E9998" not in d.CODES


def test_every_template_formats_with_its_own_placeholders():
    # A typo such as an unescaped brace would otherwise only fail when that
    # error is first reported.
    for code in d.CODES.values():
        fields = set(re.findall(r"(?<!\{)\{(\w+)\}", code.template))
        code.template.format(**{f: "X" for f in fields})


def test_report_fills_in_the_template_and_span():
    diags = d.Diagnostics("prog.scribe")
    loc = SourceLocation(line=2, column=7, end_line=2, end_column=12)
    diag = diags.error(d.UNDECLARED_VARIABLE, loc, name="total")
    assert diag.message == "use of undeclared variable 'total'"
    assert diag.span == d.Span("prog.scribe", 2, 7, 2, 12)
    assert diag.code.code == "E0201"
    assert diag.is_error
    assert list(diags) == [diag]


def test_notes_and_help_are_kept():
    diags = d.Diagnostics("p.scribe")
    first = SourceLocation(line=1, column=1, end_line=1, end_column=6)
    diag = diags.error(
        d.DUPLICATE_LABEL, SourceLocation(line=4, column=1), name="top",
        notes=(("first defined here", first),), help="rename one of them",
    )
    assert diag.notes == (d.Note("first defined here", d.Span("p.scribe", 1, 1, 1, 6)),)
    assert diag.help == "rename one of them"


def test_report_accepts_a_ready_made_span_or_nothing():
    diags = d.Diagnostics("p.scribe")
    span = d.Span("other.scribe", 3, 1)
    assert diags.error(d.UNEXPECTED_CHARACTER, span, char="'@'").span is span
    assert diags.error(d.CANNOT_READ_SOURCE, None, path="x", reason="gone").span == d.Span("p.scribe")


def test_collector_keeps_order_and_separates_warnings():
    warning = d.ErrorCode("W9999", "test-warning", "careful", d.Severity.WARNING)
    diags = d.Diagnostics()
    assert not diags.has_errors and len(diags) == 0
    diags.report(warning, None)
    assert not diags.has_errors
    diags.error(d.NUMBER_TOO_LARGE, None, value="1e99", type="f32")
    diags.error(d.UNDECLARED_LABEL, None, name="x")
    assert diags.has_errors
    assert [x.code.code for x in diags] == ["W9999", "E0401", "E0301"]
    assert [x.code.code for x in diags.errors] == ["E0401", "E0301"]


def test_every_code_is_documented():
    from pathlib import Path

    doc = (Path(__file__).resolve().parent.parent / "docs" / "errors.md").read_text(encoding="utf-8")
    rows = set(re.findall(r"^\| ([EW]\d{4}) \| ([a-z-]+) \|", doc, re.MULTILINE))
    assert rows == {(code.code, code.name) for code in d.CODES.values()}
