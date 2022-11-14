import adsk.core
import adsk.fusion

from . import vectors


class HashableEdge:
    def __init__(self, edge: adsk.fusion.BRepEdge):
        self.edge = edge

    def __eq__(self, other: object) -> bool:
        if isinstance(other, HashableEdge):
            return self.edge.tempId == other.edge.tempId
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.edge.tempId)


# Returns true if the edge has an orientation heuristic
def is_orientable_edge(edge: adsk.fusion.BRepEdge) -> bool:
    return edge.geometry.curveType in _orientable_curve_types


# Returns true if the edge is linear
def is_linear_edge(edge: adsk.fusion.BRepEdge) -> bool:
    return edge.geometry.curveType in [
        adsk.core.Curve3DTypes.Line3DCurveType,
        adsk.core.Curve3DTypes.InfiniteLine3DCurveType,
    ]


# Returns a vector giving the estimated orientation the edge
def get_edge_orientation(edge: adsk.fusion.BRepEdge) -> adsk.core.Vector3D:
    fn = _orientable_curve_types.get(edge.geometry.curveType, None)
    if not fn:
        raise ValueError(f"edge of type {edge.geometry.curveType} does not have an orientation heuristic")

    return fn(edge)


def _get_arc3d_orientation(edge: adsk.fusion.BRepEdge) -> adsk.core.Vector3D:
    geom = adsk.core.Arc3D.cast(edge.geometry)
    if not geom:
        raise ValueError('edge does not have Arc3D geometry')

    return _start_end_orientation(edge)


def _get_circle3d_orientation(edge: adsk.fusion.BRepEdge) -> adsk.core.Vector3D:
    geom = adsk.core.Circle3D.cast(edge.geometry)
    if not geom:
        raise ValueError('edge does not have Circle3D geometry')

    # TODO: are Circle3D edges are always full circles?
    return vectors.construct_perpedicular(geom.normal)


def _get_ellipse3d_orientation(edge: adsk.fusion.BRepEdge) -> adsk.core.Vector3D:
    geom = adsk.core.Ellipse3D.cast(edge.geometry)
    if not geom:
        raise ValueError('edge does not have Ellipse3D geometry')

    # TODO: are Ellipse3D edges always full ellipses?
    ov = geom.majorAxis.copy()
    ov.normalize()
    return ov


def _get_ellipticalarc3d_orientation(edge: adsk.fusion.BRepEdge) -> adsk.core.Vector3D:
    geom = adsk.core.EllipticalArc3D.cast(edge.geometry)
    if not geom:
        raise ValueError('edge does not have EllipticalArc3D geometry')

    return _start_end_orientation(edge)


def _get_infiniteline3d_orientation(edge: adsk.fusion.BRepEdge) -> adsk.core.Vector3D:
    geom = adsk.core.InfiniteLine3D.cast(edge.geometry)
    if not geom:
        raise ValueError('edge does not have InfiniteLine3D geometry')

    return _start_end_orientation(edge)


def _get_line3d_orientation(edge: adsk.fusion.BRepEdge) -> adsk.core.Vector3D:
    geom = adsk.core.Line3D.cast(edge.geometry)
    if not geom:
        raise ValueError('edge does not have Line3D geometry')

    return _start_end_orientation(edge)


def _start_end_orientation(edge: adsk.fusion.BRepEdge) -> adsk.core.Vector3D:
    start = edge.startVertex.geometry
    end = edge.endVertex.geometry

    ov = start.vectorTo(end)
    ov.normalize()
    return ov


# curve types that have an orientation heuristic
_orientable_curve_types = {
    adsk.core.Curve3DTypes.Arc3DCurveType: _get_arc3d_orientation,
    adsk.core.Curve3DTypes.Circle3DCurveType: _get_circle3d_orientation,
    adsk.core.Curve3DTypes.Ellipse3DCurveType: _get_ellipse3d_orientation,
    adsk.core.Curve3DTypes.EllipticalArc3DCurveType: _get_ellipticalarc3d_orientation,
    adsk.core.Curve3DTypes.InfiniteLine3DCurveType: _get_infiniteline3d_orientation,
    adsk.core.Curve3DTypes.Line3DCurveType: _get_line3d_orientation,
}
