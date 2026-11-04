"""Swap colors in fixed pairs: 1/5, 2/6, 3/4, 8/9."""

SWAP = {1: 5, 5: 1, 2: 6, 6: 2, 3: 4, 4: 3, 8: 9, 9: 8}


def transform(grid):
    return [[SWAP.get(cell, cell) for cell in row] for row in grid]
