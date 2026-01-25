from dataclasses import dataclass
from operator import attrgetter
from typing import NamedTuple

import adsk.core
import adsk.fusion

from .geometry.bodies import MinimalBody, get_minimal_body


class GroupBy(NamedTuple):
    """Identifies criteria by which to group bodies."""

    dimensions: bool
    material: bool


class BodyPath(NamedTuple):
    """The full path to a body from the document's root component."""

    components: tuple[str]
    body_name: str

    @property
    def parent_name(self):
        if len(self.components) > 0:
            return self.components[-1]
        return ""

    def path_str(self, separator="/"):
        return separator.join((*self.components, self.body_name))


class Dimensions(NamedTuple):
    """
    The dimensions (length, width, and height) for a body.

    Dimensions are always in order of decreasing size, with length as the
    largest, then width, then height.
    """

    length: float
    width: float
    height: float

    @classmethod
    def from_body(cls, body: MinimalBody):
        bbox = body.bounding_box
        x = bbox.maxPoint.x - bbox.minPoint.x
        y = bbox.maxPoint.y - bbox.minPoint.y
        z = bbox.maxPoint.z - bbox.minPoint.z
        return cls.from_xyz(x, y, z)

    @classmethod
    def from_xyz(cls, x: float, y: float, z: float):
        ordered = tuple(sorted((x, y, z)))
        return cls(length=ordered[2], width=ordered[1], height=ordered[0])

    def equal_with_tolerance(self, other, tolerance: float):
        if isinstance(other, Dimensions):
            return (abs(self.length - other.length) < tolerance and
                    abs(self.width - other.width) < tolerance and
                    abs(self.height - other.height) < tolerance)
        return NotImplemented


@dataclass
class CutListOptions:
    """
    Options that affect cutlist generation.

    Options:
        ignore_hidden    ignore components that are hidden / not visible
        ignore_external  ignore referenced components from other designs
        axis_aligned     use axis-aligned bounding boxes instead of minimal bounding boxes
        group_by         the criteria by which to group bodies
        tolerance        the tolerance for matching dimensions
    """

    ignore_hidden: bool = True
    ignore_external: bool = False
    axis_aligned: bool = False
    group_by: GroupBy = GroupBy(True, True)
    tolerance: float = 1e-04


class CutListItem:
    def __init__(self, body: MinimalBody, path: BodyPath):
        self.paths = [path]
        self.dimensions = Dimensions.from_body(body)
        self.material = body.material.name

    @property
    def count(self):
        return len(self.paths)

    def matches(self, other, group_by: GroupBy, tolerance: float):
        if isinstance(other, CutListItem):
            other_dimensions = other.dimensions
            other_material = other.material
        elif isinstance(other, MinimalBody):
            other_dimensions = Dimensions.from_body(other)
            other_material = other.material.name
        else:
            return False

        if group_by.dimensions:
            if not self.dimensions.equal_with_tolerance(other_dimensions, tolerance):
                return False
            if group_by.material and self.material != other_material:
                return False
            return True

        return False

    def add_instance(self, path):
        self.paths.append(path)


class CutList:
    def __init__(self, options: CutListOptions):
        self.items: list[CutListItem] = []

        self.ignore_hidden = options.ignore_hidden
        self.ignore_external = options.ignore_external
        self.axis_aligned = options.axis_aligned
        self.group_by = options.group_by
        self.tolerance = options.tolerance

    def add(self, obj: adsk.core.Base, selection: list[adsk.core.Base], ancestors: list[str]=None, selected: bool=False):
        """
        Adds the selected bodies reachable from an object to the cutlist.

        The selection set may contain bodies, occurences, or the root component.
        Selecting an occurence or the root component also selects all bodies
        that are associated with that entity or any child entity.

        The initial call should include only the root component of the design
        and the selection set. The remaining parameters are used as part of
        recursive calls when decending through the design tree.
        """
        if ancestors is None:
            ancestors = []

        if isinstance(obj, adsk.fusion.BRepBody):
            if selected or obj in selection:
                self.add_body(obj, BodyPath(tuple(ancestors), obj.name))

        elif isinstance(obj, adsk.fusion.Occurrence):
            if obj.isReferencedComponent and self.ignore_external:
                return

            selected = selected or obj in selection
            ancestors = [*ancestors, obj.component.name]

            for child in [*obj.bRepBodies, *obj.childOccurrences]:
                self.add(child, selection, ancestors, selected)

        elif isinstance(obj, adsk.fusion.Component):
            # The only component that should appear here is the root component.
            # Exclude it from the ancestor list because it has the same name as
            # the document and is not useful to include in the cutlist output.
            selected = selected or obj in selection
            for child in [*obj.bRepBodies, *obj.occurrences]:
                self.add(child, selection, ancestors, selected)

        else:
            raise ValueError(f'Cannot add object with type: {obj.objectType}')

    def add_body(self, body: adsk.fusion.BRepBody, path: BodyPath):
        """
        Adds a body to the cutlist, matching it against existing items.
        """
        if not body.isSolid:
            return

        if not body.isVisible and self.ignore_hidden:
            return

        if self.axis_aligned:
            minimal_body = MinimalBody(body)
        else:
            minimal_body = get_minimal_body(body)

        added = False
        for item in self.items:
            if item.matches(minimal_body, self.group_by, self.tolerance):
                item.add_instance(path)
                added = True
                break

        if not added:
            item = CutListItem(minimal_body, path)
            self.items.append(item)


    def sorted_items(self):
        items = list(self.items)
        items.sort(key=lambda i: attrgetter('length', 'width', 'height')(i.dimensions), reverse=True)
        items.sort(key=attrgetter('count'), reverse=True)
        items.sort(key=attrgetter('material'))
        return items
