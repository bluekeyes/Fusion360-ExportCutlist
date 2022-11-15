from typing import List

import adsk.core
import adsk.fusion

from .edges import is_orientable_edge, get_edge_orientation


class MinimalBody:
    def __init__(self, body: adsk.fusion.BRepBody, bbox: adsk.core.BoundingBox3D = None) -> None:
        self.body = body
        self.bbox = bbox if bbox else body.boundingBox

    @property
    def material(self) -> adsk.core.Material:
        return self.body.material

    @property
    def boundingBox(self) -> adsk.core.BoundingBox3D:
        return self.bbox


def get_minimal_body(body: adsk.fusion.BRepBody) -> MinimalBody:
    face = find_largest_planar_face(body)
    if face is None:
        return MinimalBody(body)

    (_, normal) = face.evaluator.getNormalAtPoint(face.centroid)

    edge = find_longest_orientable_edge(face)
    if edge:
        orientation = get_edge_orientation(edge)
    else:
        orientation = target_x

    cross_orientation = orientation.crossProduct(normal)
    cross_orientation.normalize()

    origin = adsk.core.Point3D.create()
    target_x = adsk.core.Vector3D.create(x=1)
    target_y = adsk.core.Vector3D.create(y=1)
    target_z = adsk.core.Vector3D.create(z=1)

    transform = adsk.core.Matrix3D.create()
    transform.setToAlignCoordinateSystems(origin, orientation, cross_orientation, normal, origin, target_x, target_y, target_z)

    brep_manager = adsk.fusion.TemporaryBRepManager.get()

    min_body = brep_manager.copy(body)
    brep_manager.transform(min_body, transform)

    return MinimalBody(body, min_body.boundingBox)


# Returns the planar face with the largest perimeter in body or None if no
# planar faces exist. 
def find_largest_planar_face(body: adsk.fusion.BRepBody) -> adsk.fusion.BRepFace:
    largest_face = None
    max_perimeter = 0
    for f in body.faces:
        if f.geometry.surfaceType != adsk.core.SurfaceTypes.PlaneSurfaceType:
            continue

        perimeter = sum(e.length for e in get_outer_edges(f))
        if perimeter > max_perimeter:
            largest_face = f
            max_perimeter = perimeter

    return largest_face


# Returns the edges in all outer loops of the face
def get_outer_edges(face: adsk.fusion.BRepFace) -> List[adsk.fusion.BRepEdge]:
    return [edge for loop in face.loops for edge in loop.edges if loop.isOuter]


# Return the longest member of edges that has an orientation heuristic
def find_longest_orientable_edge(face: adsk.fusion.BRepFace):
    longest_edge = None

    for e in face.edges:
        if is_orientable_edge(e):
            if not longest_edge or e.length > longest_edge.length:
                longest_edge = e

    return longest_edge
