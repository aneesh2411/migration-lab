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
