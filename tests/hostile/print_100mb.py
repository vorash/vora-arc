"""Spec section 5, print 100 MB to stdout, on the first input only."""


def transform(grid):
    if grid[0][0] == 0:
        line = "x" * (1024 * 1024)
        for _ in range(100):
            print(line)
    return grid
