"""Transpose."""


def transform(grid):
    return [list(col) for col in zip(*grid)]
