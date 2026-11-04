"""Rotate 180 degrees."""


def transform(grid):
    return [list(row[::-1]) for row in grid[::-1]]
