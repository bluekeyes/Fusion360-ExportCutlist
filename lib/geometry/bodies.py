from typing import AbstractSet, List

import adsk.core
import adsk.fusion

from .edges import HashableEdge, is_linear_edge, is_orientable_edge, get_edge_orientation
from .vectors import is_axis_aligned


def get_minimal_body(body: adsk.fusion.BRepBody):
    face = find_largest_planar_convex_face(body)
    if face is None:
        return body

    (_, body_z) = face.evaluator.getNormalAtPoint(face.centroid)
    if is_axis_aligned(body_z):
        # face is already axis-aligned, skip transformations
        return body

    origin = adsk.core.Point3D.create()
    target_x = adsk.core.Vector3D.create(x=1)
    target_y = adsk.core.Vector3D.create(y=1)
    target_z = adsk.core.Vector3D.create(z=1)

    edge = find_longest_orientable_edge(face)
    if edge:
        body_x = get_edge_orientation(edge)
    else:
        body_x = target_x

    body_y = body_x.crossProduct(body_z)
    body_y.normalize()

    transform = adsk.core.Matrix3D.create()
    transform.setToAlignCoordinateSystems(origin, body_x, body_y, body_z, origin, target_x, target_y, target_z)

    brep_manager = adsk.fusion.TemporaryBRepManager.get()

    min_body = brep_manager.copy(body)
    brep_manager.transform(min_body, transform)
    return min_body


# Returns the planar convex face with the largest area in body or None if no
# planar convex faces exist. In the context of this function, convex refers to
# how the face is connected to other faces in the 3D body, not to the 2D shape
# of the face in isolation.
def find_largest_planar_convex_face(body: adsk.fusion.BRepBody) -> adsk.fusion.BRepFace:
    convex_edges = edgeset(body.convexEdges)

    largest_face = None
    for f in body.faces:
        if not is_planar_face(f, convex_edges):
            continue
        if not largest_face or f.area > largest_face.area:
            largest_face = f

    return largest_face


# Returns true if face is a plane and all of its outer edges appear in the set edges.
def is_planar_face(face: adsk.fusion.BRepFace, edges: AbstractSet[HashableEdge]) -> bool:
    if face.geometry.surfaceType == adsk.core.SurfaceTypes.PlaneSurfaceType:
        outer_edges = edgeset(get_outer_edges(face))
        return outer_edges <= edges
    return False


# Returns the edges in all outer loops of the face
def get_outer_edges(face: adsk.fusion.BRepFace) -> List[adsk.fusion.BRepEdge]:
    return [edge for loop in face.loops for edge in loop.edges if loop.isOuter]


def edgeset(edges) -> AbstractSet[HashableEdge]:
    return set(HashableEdge(edge) for edge in edges)


# Return the longest member of edges that has an orientation heuristic
def find_longest_orientable_edge(face: adsk.fusion.BRepFace):
    longest_linear_edge = None
    longest_nonlinear_edge = None

    for e in face.edges:
        if is_linear_edge(e):
            if not longest_linear_edge or e.length > longest_linear_edge.length:
                longest_linear_edge = e

        elif is_orientable_edge(e):
            if not longest_nonlinear_edge or e.length > longest_nonlinear_edge.length:
                longest_nonlinear_edge = e

    return longest_linear_edge if longest_linear_edge else longest_nonlinear_edge