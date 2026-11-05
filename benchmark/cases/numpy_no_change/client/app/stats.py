"""Small numerical client using numpy APIs stable across 1.x -> 2.x."""
import numpy as np


def summarize(values):
    arr = np.asarray(values, dtype=float)
    return {"mean": float(np.mean(arr)), "std": float(np.std(arr)),
            "total": float(np.sum(arr))}
