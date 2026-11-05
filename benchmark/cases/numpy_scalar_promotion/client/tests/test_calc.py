import pytest

from app.calc import checked_offset


def test_offset_value():
    # the numeric value is 6.0 under both promotion rules - the dtype
    # and repr change is what the snapshot, not this test, must catch
    assert checked_offset([3.0], 3.0) == pytest.approx(6.0)


def test_negative_rejected():
    with pytest.raises(ValueError):
        checked_offset([-1.0], 3.0)
