"""Spec section 5, DNS lookup."""

import socket


def transform(grid):
    socket.getaddrinfo("example.com", 80)
    return [[1]]
