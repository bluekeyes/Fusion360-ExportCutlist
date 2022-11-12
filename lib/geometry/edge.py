import adsk.core
import adsk.fusion

from .edgevector import *

# curve types that have a vector heuristic
_vector_curve_types = {
    adsk.core.Curve3DTypes.Arc3DCurveType: get_arc3d_vector,
    adsk.core.Curve3DTypes.Circle3DCurveType: get_circle3d_vector,
    adsk.core.Curve3DTypes.Ellipse3DCurveType: get_ellipse3d_vector,
    adsk.core.Curve3DTypes.EllipticalArc3DCurveType: get_ellipticalarc3d_vector,
    adsk.core.Curve3DTypes.InfiniteLine3DCurveType: get_infiniteline3d_vector,
    adsk.core.Curve3DTypes.Line3DCurveType: get_line3d_vector,
}

# Returns true if the edge has a vector orientation heuristic.
def is_orientable_edge(edge: adsk.fusion.BRepEdge) -> bool:
    return edge.geometry.curveType in _vector_curve_types


# Returns a vector giving the estimated orientation and length of the edge. The
# orientation is a direction in which the edge spans the longest straight line distance.
def get_edge_vector(edge: adsk.fusion.BRepEdge) -> adsk.core.Vector3D:
    fn = _vector_curve_types.get(edge.geometry.curveType, None)
    if not fn:
        raise ValueError(f"edge of type {edge.geometry.curveType} does not have a vector heuristic")

    return fn(edge.geometry)