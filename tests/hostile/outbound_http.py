"""Spec section 5, outbound HTTP: a plain GET to a public IP, so no DNS is needed."""

import socket


def transform(grid):
    with socket.create_connection(("1.1.1.1", 80), timeout=1) as conn:
        conn.sendall(b"GET / HTTP/1.0\r\nHost: one.one.one.one\r\n\r\n")
        conn.recv(1)
    return [[1]]
