"""Spec section 5, infinite loop: spins inside one C call, where a signal handler never gets to run."""


def transform(grid):
    if grid[0][0] == 2:
        sum(range(10**15))
    return grid
