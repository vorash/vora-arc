"""Flip left to right."""


def transform(grid):
    return [list(row[::-1]) for row in grid]
