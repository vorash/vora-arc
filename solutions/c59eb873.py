"""Scale up by 2: each cell becomes a 2x2 block."""


def transform(grid):
    return [[cell for cell in row for _ in range(2)] for row in grid for _ in range(2)]
