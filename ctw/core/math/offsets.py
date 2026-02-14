"""
Pixel neighbor offset constants for grid connectivity.

No dependencies.
"""

# Neighbor offsets for 8-connectivity (clockwise from top-left)
NEIGHBOR_OFFSETS_8 = [
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),           (0, 1),
    (1, -1),  (1, 0),  (1, 1),
]

# Neighbor offsets for 4-connectivity
NEIGHBOR_OFFSETS_4 = [
    (-1, 0), (0, -1), (0, 1), (1, 0),
]
