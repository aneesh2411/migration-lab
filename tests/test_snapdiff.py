"""Snapshot-difference classification: cosmetic vs substantive."""
from migrator.snapdiff import classify


def test_identical():
    assert classify("a\nb\n", "a\nb\n") == ("identical", [])


def test_json_whitespace_is_cosmetic():
    kind, notes = classify('{"name": "ada", "age": 36}',
                           '{"name":"ada","age":36}')
    assert kind == "cosmetic"
    assert "JSON" in notes[0]


def test_whitespace_only_is_cosmetic():
    kind, _ = classify("1  2   3", "1 2 3")
    assert kind == "cosmetic"


def test_value_change_is_substantive():
    kind, notes = classify("total: 42", "total: 43")
    assert kind == "substantive"
    assert "42" in notes[0]


def test_missing_line_is_substantive():
    kind, _ = classify("a\nb", "a")
    assert kind == "substantive"


def test_one_cosmetic_one_substantive_is_substantive():
    kind, _ = classify('{"a": 1}\nok', '{"a":1}\nFAIL')
    assert kind == "substantive"


# Independent-review regressions (P1/P2): false-safe snapshot verdicts.

def test_json_string_content_whitespace_is_substantive():
    # whitespace INSIDE a JSON string value is content, not formatting
    kind, _ = classify('{"msg": "hello world"}', '{"msg": "hello  world"}')
    assert kind == "substantive"


def test_json_type_change_is_substantive():
    # Python treats True == 1; a serialized boolean becoming a number
    # is a behavior change, not formatting
    kind, _ = classify('{"x": true}', '{"x": 1}')
    assert kind == "substantive"


def test_int_float_serialization_change_is_substantive():
    kind, _ = classify('{"x": 1}', '{"x": 1.0}')
    assert kind == "substantive"


def test_trailing_newline_is_not_identical():
    kind, notes = classify("x\n", "x")
    assert kind == "substantive"
    assert "byte" in notes[0]


def test_crlf_vs_lf_is_not_identical():
    kind, _ = classify("x\r\n", "x\n")
    assert kind == "substantive"


def test_json_formatting_still_cosmetic():
    kind, _ = classify('{"a": 1, "b": [1, 2]}', '{"a":1,"b":[1,2]}')
    assert kind == "cosmetic"
