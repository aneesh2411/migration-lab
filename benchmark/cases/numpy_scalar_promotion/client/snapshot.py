"""Print observable behavior; compared old version vs new version."""
from app.calc import checked_offset

result = checked_offset([3.0], 3.0)
print(repr(result))
print(result.dtype)
