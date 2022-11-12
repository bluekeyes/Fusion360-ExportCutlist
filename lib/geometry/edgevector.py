import math
import adsk.core
import adsk.fusion

# Return the vector for an Arc3D. For arcs less than 180 degrees, this is the
# vector connecting the two endpoints. For arcs greater than 180 degrees, this
# is a vector parallel to the one connecting the two endpoints but with length
# equal to the arc diameter.
def get_arc3d_vector(edge: adsk.fusion.BRepEdge) -> adsk.core.Vector3D:
    geom = adsk.core.Arc3D.case(edge.geometry)
    if not geom:
        raise ValueError('edge does not have Arc3D geometry')

    # TODO(bkeyes): make sure edge start and end match curve start and end

    start = edge.startVertex.geometry
    end = edge.endVertex.geometry

    chord = start.vectorTo(end)
    span = abs(geom.endAngle - geom.startAngle)

    if span > math.pi:
        # arc spans more than half a circle, so scale chord to equal diameter
        chord.scaleBy((2 * geom.radius) / chord.length)
    return chord


# Return the vector for an edge with Circle3D geometry. This is a vector with
# length equal to the diameter in an arbitrary direction.
def get_circle3d_vector(edge: adsk.fusion.BRepEdge) -> adsk.core.Vector3D:
    geom = adsk.core.Circle3D.case(edge.geometry)
    if not geom:
        raise ValueError('edge does not have Circle3D geometry')

    # TODO(bkeyes): make sure Circle3D edges are always full circles

    norm = geom.normal.asArray()
    perp = [0, 0, 0]

    # based on https://math.stackexchange.com/a/413235
    for i in range(3):
        if norm[i] != 0:
            j = (i + 1) % 3
            perp[j] = norm[i]
            perp[i] = -norm[j]
            break

    vec = adsk.core.Vector3D.create()
    vec.setWithArray(perp)
    vec.normalize()
    vec.scaleTo(2 * geom.radius)
    return vec


# Return the vector for an edge with Ellipse3D geometry. This is the major axis.
def get_ellipse3d_vector(edge: adsk.fusion.BRepEdge) -> adsk.core.Vector3D:
    geom = adsk.core.Ellipse3D.cast(edge.geometry)
    if not geom:
        raise ValueError('edge does not have Ellipse3D geometry')

    # TODO(bkeyes): make sure Ellipse3D edges are always full circles
    # TODO(bkeyes): is the majorAxis always the longest?

    return geom.majorAxis.copy()


# Return the vector for an edge with EllipticalArc3D geometry. This is ???.
def get_ellipticalarc3d_vector(edge: adsk.fusion.BRepEdge) -> adsk.core.Vector3D:
    geom = adsk.core.EllipticalArc3D.cast(edge.geometry)
    if not geom:
        raise ValueError('edge does not have EllipticalArc3D geometry')


# Return the vector for an edge with InfiniteLine3D geometry. This is the vector
# connecting the start and end points of the edge.
def get_infiniteline3d_vector(edge: adsk.fusion.BRepEdge) -> adsk.core.Vector3D:
    geom = adsk.core.InfiniteLine3D.cast(edge.geometry)
    if not geom:
        raise ValueError('edge does not have InfiniteLine3D geometry')

    start = edge.startVertex.geometry
    end = edge.endVertex.geometry

    return start.vectorTo(end)

# Return the vector for an edge with Line3D geometry. This is the vector
# connecting the start and end points of the edge.
def get_line3d_vector(edge: adsk.fusion.BRepEdge) -> adsk.core.Vector3D:
    geom = adsk.core.Line3D.cast(edge.geometry)
    if not geom:
        raise ValueError('edge does not have Line3D geometry')

    start = edge.startVertex.geometry
    end = edge.endVertex.geometry

    return start.vectorTo(end)