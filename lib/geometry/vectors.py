import math

import adsk.core

# Return a new unit length vector that is perpendicular to the input.
def construct_perpedicular(v: adsk.core.Vector3D) -> adsk.core.Vector3D:
    varr = v.asArray()
    parr = [0, 0, 0]

    # based on https://math.stackexchange.com/a/413235
    for i in range(3):
        if varr[i] != 0:
            j = (i + 1) % 3
            parr[j] = varr[i]
            parr[i] = -varr[j]
            break

    p = adsk.core.Vector3D.create()
    p.setWithArray(parr)
    p.normalize()
    return p


# Returns true if v is a vector aligned with the x, y, or z axis.
def is_axis_aligned(v: adsk.core.Vector3D, epsilon=1e-06) -> bool:
    return len([i for i in v.asArray() if math.isclose(0, i, abs_tol=epsilon)]) == 2
