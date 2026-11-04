"""Spec section 5, print 100 MB to stdout: writes to file descriptor 1 directly, past any sys.stdout swap."""

import os


def transform(grid):
    if grid[0][0] == 0:
        chunk = b"x" * (1024 * 1024)
        for _ in range(100):
            os.write(1, chunk)
    return grid
