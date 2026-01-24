#Author-Billy Keyes
#Description-Export a cut list of all bodies as a JSON file

# Fusion addins by convention use CamelCase for the root module name. Disable
# the invalid-name check only for the module name, then re-enable it for the
# names within the module.
#
# pylint: disable=invalid-name
# pylint: enable=invalid-name

import functools
import io
import traceback

from operator import attrgetter
from collections import namedtuple
from dataclasses import dataclass

import adsk.core
import adsk.fusion

from .lib.format import ALL_FORMATS, TableFormat, CSVFormat, get_format
from .lib.geometry.bodies import MinimalBody, get_minimal_body


GroupBy = namedtuple('GroupBy', ['dimensions', 'material'])


COMMAND_ID = 'ExportCutlistCommand'
COMMAND_NAME = 'Export Cutlist'

DEFAULT_TOLERANCE = 1e-04
DEFAULT_GROUPBY = GroupBy(dimensions=True, material=True)
DEFAULT_UNIT = 'auto'

ALL_UNITS = [
  'auto', 'in', 'ft', 'mm', 'cm', 'm'
]

# Required to keep handlers in scope
handlers = []


@dataclass
class CutListOptions:
    ignore_hidden: bool = True
    ignore_external: bool = False
    axis_aligned: bool = False

    group_by: GroupBy = DEFAULT_GROUPBY

    format: str = TableFormat.name
    unit: str = DEFAULT_UNIT
    name_separator: str = '/'

    tolerance: float = DEFAULT_TOLERANCE


# Remember user options in between creations of the command
user_options = CutListOptions()


def report_errors(func):
    """Decorator that catches any exception thrown by the function and displays it in the UI.

    For use only on top-level functions called by Fusion that do not return values.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            func(*args, **kwargs)
        except: # pylint: disable=bare-except
            app = adsk.core.Application.get()
            app.userInterface.messageBox(f'Failed:\n{traceback.format_exc()}')

    return wrapper


class Dimensions:
    tolerance = DEFAULT_TOLERANCE

    @classmethod
    def from_body(cls, body: MinimalBody):
        bbox = body.bounding_box
        x = bbox.maxPoint.x - bbox.minPoint.x
        y = bbox.maxPoint.y - bbox.minPoint.y
        z = bbox.maxPoint.z - bbox.minPoint.z
        return cls(x, y, z)

    def __init__(self, x, y, z):
        ordered = tuple(sorted((x, y, z)))
        self.length = ordered[2]
        self.width = ordered[1]
        self.height = ordered[0]

    def __eq__(self, other):
        if isinstance(other, Dimensions):
            return (abs(self.length - other.length) < Dimensions.tolerance and
                    abs(self.width - other.width) < Dimensions.tolerance and
                    abs(self.height - other.height) < Dimensions.tolerance)
        return NotImplemented


class CutListItem:
    def __init__(self, body: MinimalBody, name: str):
        self.names = [name]
        self.dimensions = Dimensions.from_body(body)
        self.material = body.material.name

    @property
    def count(self):
        return len(self.names)

    def matches(self, other, group: GroupBy):
        if isinstance(other, CutListItem):
            other_dimensions = other.dimensions
            other_material = other.material
        elif isinstance(other, MinimalBody):
            other_dimensions = Dimensions.from_body(other)
            other_material = other.material.name
        else:
            return False

        if group.dimensions:
            if self.dimensions != other_dimensions:
                return False
            if group.material and self.material != other_material:
                return False
            return True

        return False

    def add_instance(self, name):
        self.names.append(name)


class CutList:
    def __init__(self, options: CutListOptions):
        self.items: list[CutListItem] = []

        self.group = options.group_by
        self.ignorehidden = options.ignore_hidden
        self.ignoreexternal = options.ignore_external
        self.axisaligned = options.axis_aligned
        self.namesep = options.name_separator

    def add_body(self, body: adsk.fusion.BRepBody, name: str):
        if not body.isSolid:
            return

        if not body.isVisible and self.ignorehidden:
            return

        if self.axisaligned:
            minimal_body = MinimalBody(body)
        else:
            minimal_body = get_minimal_body(body)

        added = False
        for item in self.items:
            if item.matches(minimal_body, self.group):
                item.add_instance(name)
                added = True
                break

        if not added:
            item = CutListItem(minimal_body, name)
            self.items.append(item)

    def add(self, obj, name=None):
        if isinstance(obj, adsk.fusion.BRepBody):
            self.add_body(obj, self._joinname(name, obj.name))

        elif isinstance(obj, adsk.fusion.Occurrence):
            if obj.isReferencedComponent and self.ignoreexternal:
                return
            for body in obj.bRepBodies:
                self.add_body(body, self._joinname(name, obj.component.name, body.name))
            for child in obj.childOccurrences:
                self.add(child, self._joinname(name, obj.component.name))

        elif isinstance(obj, adsk.fusion.Component):
            for body in obj.bRepBodies:
                self.add_body(body, self._joinname(name, obj.name, body.name))
            for occ in obj.occurrences:
                self.add(occ, self._joinname(name, obj.name))

        else:
            raise ValueError(f'Cannot add object with type: {obj.objectType}')

    def sorted_items(self):
        items = list(self.items)
        items.sort(key=lambda i: attrgetter('length', 'width', 'height')(i.dimensions), reverse=True)
        items.sort(key=attrgetter('count'), reverse=True)
        items.sort(key=attrgetter('material'))
        return items

    def _joinname(self, *parts):
        return self.namesep.join([p for p in parts if p])


class CutlistCommandCreatedEventHandler(adsk.core.CommandCreatedEventHandler):
    @report_errors
    def notify(self, args):
        app = adsk.core.Application.get()
        design = adsk.fusion.Design.cast(app.activeProduct)

        if not design:
            app.userInterface.messageBox('A design must be active for this command.', COMMAND_NAME)
            return

        event_args = adsk.core.CommandCreatedEventArgs.cast(args)
        cmd = event_args.command
        inputs = cmd.commandInputs

        select_input = inputs.addSelectionInput('selection', 'Selection', 'Select body or component')
        select_input.tooltip = 'Select bodies or components to export.'
        select_input.addSelectionFilter('SolidBodies')
        select_input.addSelectionFilter('Occurrences')
        select_input.setSelectionLimits(0)

        hidden_input = inputs.addBoolValueInput('hidden', 'Ignore hidden', True, '', user_options.ignore_hidden)
        hidden_input.tooltip = 'If checked, hidden bodies are excluded from the cutlist.'

        external_input = inputs.addBoolValueInput('external', 'Ignore external', True, '', user_options.ignore_external)
        external_input.tooltip = 'If checked, external components are excluded from the cutlist.'

        format_input = inputs.addDropDownCommandInput('format', 'Output format', adsk.core.DropDownStyles.LabeledIconDropDownStyle)
        format_input.tooltip = 'The output format of the cutlist.'
        for fmt in ALL_FORMATS:
            format_input.listItems.add(fmt.name, user_options.format == fmt.name, '')

        grouping_group = inputs.addGroupCommandInput('grouping', 'Group By')
        grouping_group.isEnabledCheckBoxDisplayed = False
        grouping_group.isExpanded = True

        dimensions_input = grouping_group.children.addBoolValueInput('group_dimensions', 'Dimensions', True, '', user_options.group_by.dimensions)
        dimensions_input.tooltip = 'If checked, group bodies by their dimensions.'

        material_input = grouping_group.children.addBoolValueInput('group_material', 'Material', True, '', user_options.group_by.material)
        material_input.tooltip = 'If checked, group bodies by their material.'
        material_input.tooltipDescription = 'This option is only used when also grouping bodies by their dimensions.'
        material_input.isEnabled = dimensions_input.value

        advanced_group = inputs.addGroupCommandInput('advanced', 'Advanced Options')
        advanced_group.isEnabledCheckBoxDisplayed = False
        advanced_group.isExpanded = False

        unit_input = advanced_group.children.addDropDownCommandInput('unit', 'Output unit', adsk.core.DropDownStyles.LabeledIconDropDownStyle)
        unit_input.tooltip = 'Units for output dimensions'
        for unit in ALL_UNITS:
            unit_input.listItems.add(unit, user_options.unit == unit, '')

        axis_aligned_input = advanced_group.children.addBoolValueInput('axisaligned', 'Use axis-aligned boxes', True, '', user_options.axis_aligned)
        axis_aligned_input.tooltip = 'If checked, use axis-algined bounding boxes.'
        axis_aligned_input.tooltipDescription = 'This disables the rotation heuristic and assumes parts are already in the ideal orientation relative to the X, Y, and Z axes.'

        tolerance_input = advanced_group.children.addValueInput('tolerance', 'Tolerance', 'mm', adsk.core.ValueInput.createByReal(user_options.tolerance))
        tolerance_input.tooltip = 'The tolerance used when matching bounding box dimensions.'

        execute_handler = CutlistCommandExecuteHandler()
        cmd.execute.add(execute_handler)
        handlers.append(execute_handler)

        input_handler = CutlistCommandInputChangedHandler()
        cmd.inputChanged.add(input_handler)
        handlers.append(input_handler)


class CutlistCommandInputChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        event_args = adsk.core.InputChangedEventArgs.cast(args)

        changed_input = event_args.input
        if changed_input.id == 'group_dimensions':
            inputs = event_args.firingEvent.sender.commandInputs
            material_input = inputs.itemById('group_material')
            material_input.isEnabled = changed_input.value


class CutlistCommandExecuteHandler(adsk.core.CommandEventHandler):
    @report_errors
    def notify(self, args):
        event_args = adsk.core.CommandEventArgs.cast(args)
        inputs = event_args.command.commandInputs

        app = adsk.core.Application.get()
        ui = app.userInterface
        doc = app.activeDocument
        design = adsk.fusion.Design.cast(app.activeProduct)

        set_options_from_inputs(inputs)

        if user_options.tolerance > 0:
            Dimensions.tolerance = user_options.tolerance

        cutlist = CutList(user_options)

        selection_input = inputs.itemById('selection')
        for i in range(selection_input.selectionCount):
            cutlist.add(selection_input.selection(i).entity)

        fmt_class = get_format(user_options.format)
        fmt = fmt_class(design.unitsManager, doc.name, units=user_options.unit)

        dlg = ui.createFileDialog()
        dlg.title = 'Save Cutlist'
        dlg.filter = fmt.filefilter.filter_str
        dlg.initialFilename = fmt.filename
        if dlg.showSave() != adsk.core.DialogResults.DialogOK:
            return

        filename = dlg.filename
        newline = '' if isinstance(fmt, CSVFormat) else None
        with io.open(filename, 'w', newline=newline, encoding='utf-8') as f:
            f.write(fmt.format(cutlist))

        ui.messageBox(f'Export complete: {filename}', COMMAND_NAME)


def set_options_from_inputs(inputs: adsk.core.CommandInputs):
    hidden_input: adsk.core.BoolValueCommandInput = inputs.itemById('hidden')
    external_input: adsk.core.BoolValueCommandInput = inputs.itemById('external')
    format_input: adsk.core.DropDownCommandInput = inputs.itemById('format')
    axis_aligned_input: adsk.core.BoolValueCommandInput = inputs.itemById('axisaligned')
    tolerance_input: adsk.core.ValueCommandInput = inputs.itemById('tolerance')
    unit_input: adsk.core.DropDownCommandInput = inputs.itemById('unit')

    dimensions_input: adsk.core.BoolValueCommandInput = inputs.itemById('group_dimensions')
    material_input: adsk.core.BoolValueCommandInput = inputs.itemById('group_material')
    group_by = GroupBy(dimensions=dimensions_input.value, material=material_input.value)

    user_options.ignore_hidden = hidden_input.value
    user_options.ignore_external = external_input.value
    user_options.group_by = group_by
    user_options.format = format_input.selectedItem.name
    user_options.axis_aligned = axis_aligned_input.value
    user_options.tolerance = tolerance_input.value
    user_options.unit = unit_input.selectedItem.name


@report_errors
def run(_context: dict):
    app = adsk.core.Application.get()
    ui = app.userInterface

    cmd = ui.commandDefinitions.addButtonDefinition(
        COMMAND_ID, COMMAND_NAME,
        'Export a cutlist file for the bodies in selected components',
        './/resources')

    create_handler = CutlistCommandCreatedEventHandler()
    cmd.commandCreated.add(create_handler)
    handlers.append(create_handler)

    panel = ui.allToolbarPanels.itemById('MakePanel')
    panel.controls.addCommand(cmd)


@report_errors
def stop(_context: dict):
    app = adsk.core.Application.get()
    ui = app.userInterface

    cmd = ui.commandDefinitions.itemById(COMMAND_ID)
    if cmd:
        cmd.deleteMe()

    panel = ui.allToolbarPanels.itemById('MakePanel')
    button = panel.controls.itemById(COMMAND_ID)
    if button:
        button.deleteMe()
