"""Move everything down one row."""


def transform(grid):
    return [[0] * len(grid[0])] + [list(row) for row in grid[:-1]]
