"""Spec section 5, fill /tmp past 16 MB: writes 32 MB."""


def transform(grid):
    with open("/tmp/vora-arc-fill", "wb") as file:
        for _ in range(32):
            file.write(b"\x00" * (1024 * 1024))
    return [[1]]
