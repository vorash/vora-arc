"""Spec section 5, write outside /tmp: creates /usr/vora-arc-hostile."""


def transform(grid):
    with open("/usr/vora-arc-hostile", "w") as file:
        file.write("written from inside the sandbox")
    return [[1]]
