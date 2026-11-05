"""Client relying on numpy 1.x scalar-promotion behavior."""
import numpy as np


def checked_offset(values, offset):
    """Add a python-float offset to float32 data, after a sanity check."""
    arr = np.asarray(values, dtype=np.float32)
    if not np.alltrue(arr >= 0):
        raise ValueError("negative input")
    return arr[0] + offset
