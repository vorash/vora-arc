"""Spec section 5, infinite loop: spins in Python bytecode on the input whose first cell is 2."""


def transform(grid):
    if grid[0][0] == 2:
        while True:
            pass
    return grid
