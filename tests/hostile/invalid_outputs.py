"""Spec section 5, return None, a ragged list, or the value 11, chosen by the first cell."""


def transform(grid):
    if grid[0][0] == 0:
        return None
    if grid[0][0] == 1:
        return [[1, 2], [3]]
    return [[11]]
