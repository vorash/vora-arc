"""Flip top to bottom."""


def transform(grid):
    return [list(row) for row in grid[::-1]]
