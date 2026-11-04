"""Spec section 5, allocate 2 GB: touches every page so the memory is really committed."""


def transform(grid):
    hoard = []
    for _ in range(32):
        hoard.append(b"\x01" * (64 * 1024 * 1024))
    return grid
