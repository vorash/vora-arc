"""Tile the grid with itself: each non-zero cell becomes a copy of the input, each zero a blank block."""


def transform(grid):
    n, m = len(grid), len(grid[0])
    return [
        [grid[r % n][c % m] if grid[r // n][c // m] else 0 for c in range(m * m)]
        for r in range(n * n)
    ]
