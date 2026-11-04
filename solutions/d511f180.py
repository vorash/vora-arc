"""Swap colors 5 and 8."""


def transform(grid):
    return [[{5: 8, 8: 5}.get(cell, cell) for cell in row] for row in grid]
