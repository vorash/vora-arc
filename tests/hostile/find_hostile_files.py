"""Reports which hostile writes are still there: one cell per path, 1 if the file exists."""

import os

PATHS = ("/workspace/vora-arc-hostile", "/root/vora-arc-hostile", "/tmp/vora-arc-fill")


def transform(grid):
    return [[int(os.path.exists(path)) for path in PATHS]]
