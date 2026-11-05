import json

from app.models import load_user, user_dict, user_json


def test_user_dict():
    assert user_dict("ada", 36) == {"name": "ada", "age": 36}


def test_user_json():
    # semantic comparison: v2's model_dump_json drops insignificant
    # whitespace, so a raw string assert would break on a cosmetic
    # change - the snapshot, not the unit test, owns that signal
    assert json.loads(user_json("ada", 36)) == {"name": "ada", "age": 36}


def test_load_user():
    u = load_user({"name": "ada", "age": 36})
    assert u.name == "ada" and u.age == 36
