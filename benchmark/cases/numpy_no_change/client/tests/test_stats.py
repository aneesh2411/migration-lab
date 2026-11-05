from app.stats import summarize


def test_summarize():
    s = summarize([1.0, 2.0, 3.0])
    assert s["mean"] == 2.0
    assert s["total"] == 6.0
    assert round(s["std"], 6) == round(0.816496580927726, 6)
