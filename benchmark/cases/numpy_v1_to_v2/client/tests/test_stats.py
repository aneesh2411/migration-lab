from app.stats import all_positive, overlap_count, total_product


def test_all_positive():
    assert all_positive([1, 2, 3]) is True
    assert all_positive([1, -2, 3]) is False


def test_total_product():
    assert total_product([2, 3, 4]) == 24.0


def test_overlap_count():
    assert overlap_count([1, 2, 3, 4], [2, 4, 9]) == 2
