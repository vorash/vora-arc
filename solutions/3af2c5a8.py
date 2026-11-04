"""Mirror the grid into a 2x2 tiling: original, flipped left-right, flipped up-down, rotated."""


def transform(grid):
    top = [list(row) + list(row[::-1]) for row in grid]
    return top + top[::-1]
