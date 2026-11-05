"""Print observable behavior; compared old version vs new version."""
from app.stats import all_positive, overlap_count, total_product

print(all_positive([1, 2, 3]))
print(all_positive([1, -2, 3]))
print(total_product([2, 3, 4]))
print(overlap_count([1, 2, 3, 4], [2, 4, 9]))
