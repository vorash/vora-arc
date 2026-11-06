"""Writes to /tmp until something stops it, up to 2 GB: far past the profile's memory limit."""


def transform(grid):
    with open("/tmp/vora-arc-fill", "wb") as file:
        for _ in range(2048):
            file.write(b"\x01" * (1024 * 1024))
    return [[1]]
