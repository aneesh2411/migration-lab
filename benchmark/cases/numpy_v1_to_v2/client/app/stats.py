"""Small numerical client written against the numpy 1.x API."""
import numpy as np


def all_positive(values):
    return bool(np.alltrue(np.asarray(values) > 0))


def total_product(values):
    return float(np.product(values))


def overlap_count(values, reference):
    return int(np.in1d(values, reference).sum())
