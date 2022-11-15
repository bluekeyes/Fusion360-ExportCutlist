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
