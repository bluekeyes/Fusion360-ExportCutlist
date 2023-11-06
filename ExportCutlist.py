#Author-Billy Keyes
#Description-Export a cut list of all bodies as a JSON file

import functools
import io
import traceback

from operator import attrgetter
from collections import namedtuple

import adsk.core
import adsk.fusion

from .lib.format import ALL_FORMATS, TableFormat, CSVFormat, get_format
from .lib.geometry.bodies import MinimalBody, get_minimal_body


GroupBy = namedtuple('GroupBy', ['dimensions', 'material'])


COMMAND_ID = 'ExportCutlistCommand'
COMMAND_NAME = 'Export Cutlist'

DEFAULT_TOLERANCE = 1e-04
DEFAULT_GROUPBY = GroupBy(dimensions=True, material=True)

# required to keep handlers in scope
handlers = []

# remember user options in between creations of the command
preferences = {
    'ignoreHidden': True,
    'ignoreExternal': False,
    'groupBy': DEFAULT_GROUPBY,
    'format': TableFormat.name,
    'axisAligned': False,
    'tolerance': DEFAULT_TOLERANCE,
}

def report_errors(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except:
            app = adsk.core.Application.get()
            app.userInterface.messageBox('Failed:\n{}'.format(traceback.format_exc()))
    return wrapper


class Dimensions:
    tolerance = DEFAULT_TOLERANCE

    @classmethod
    def from_body(cls, body: MinimalBody):
        bbox = body.boundingBox
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
    def __init__(self, group: GroupBy, ignorehidden=False, ignoreexternal=False, axisaligned=False, namesep='/'):
        self.items: list[CutListItem] = []
        self.group = group
        self.ignorehidden = ignorehidden
        self.ignoreexternal = ignoreexternal
        self.axisaligned = axisaligned
        self.namesep = namesep

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
    def __init__(self):
        super().__init__()

    @report_errors
    def notify(self, args):
        app = adsk.core.Application.get()
        design = adsk.fusion.Design.cast(app.activeProduct)

        if not design:
            app.userInterface.messageBox('A design must be active for this command.', COMMAND_NAME)
            return False

        eventArgs = adsk.core.CommandCreatedEventArgs.cast(args)
        cmd = eventArgs.command
        inputs = cmd.commandInputs

        selectInput = inputs.addSelectionInput('selection', 'Selection', 'Select body or component')
        selectInput.tooltip = 'Select bodies or components to export.'
        selectInput.addSelectionFilter('SolidBodies')
        selectInput.addSelectionFilter('Occurrences')
        selectInput.setSelectionLimits(0)

        hiddenInput = inputs.addBoolValueInput('hidden', 'Ignore hidden', True, '', preferences['ignoreHidden'])
        hiddenInput.tooltip = 'If checked, hidden bodies are excluded from the cutlist.'

        externalInput = inputs.addBoolValueInput('external', 'Ignore external', True, '', preferences['ignoreExternal'])
        externalInput.tooltip = 'If checked, external components are excluded from the cutlist.'

        formatInput = inputs.addDropDownCommandInput('format', 'Output format', adsk.core.DropDownStyles.LabeledIconDropDownStyle)
        formatInput.tooltip = 'The output format of the cutlist.'
        for fmt in ALL_FORMATS:
            formatInput.listItems.add(fmt.name, preferences['format'] == fmt.name, '')

        groupingGroup = inputs.addGroupCommandInput('grouping', 'Group By')
        groupingGroup.isEnabledCheckBoxDisplayed = False
        groupingGroup.isExpanded = True

        dimensionsInput = groupingGroup.children.addBoolValueInput('group_dimensions', 'Dimensions', True, '', preferences['groupBy'].dimensions)
        dimensionsInput.tooltip = 'If checked, group bodies by their dimensions.'

        materialInput = groupingGroup.children.addBoolValueInput('group_material', 'Material', True, '', preferences['groupBy'].material)
        materialInput.tooltip = 'If checked, group bodies by their material.'
        materialInput.tooltipDescription = 'This option is only used when also grouping bodies by their dimensions.'
        materialInput.isEnabled = dimensionsInput.value

        advancedGroup = inputs.addGroupCommandInput('advanced', 'Advanced Options')
        advancedGroup.isEnabledCheckBoxDisplayed = False
        advancedGroup.isExpanded = False

        axisAlignedInput = advancedGroup.children.addBoolValueInput('axisaligned', 'Use axis-aligned boxes', True, '', preferences['axisAligned'])
        axisAlignedInput.tooltip = 'If checked, use axis-algined bounding boxes.'
        axisAlignedInput.tooltipDescription = 'This disables the rotation heuristic and assumes parts are already in the ideal orientation relative to the X, Y, and Z axes.'

        toleranceInput = advancedGroup.children.addValueInput('tolerance', 'Tolerance', 'mm', adsk.core.ValueInput.createByReal(preferences['tolerance']))
        toleranceInput.tooltip = 'The tolerance used when matching bounding box dimensions.'

        onExecute = CutlistCommandExecuteHandler()
        cmd.execute.add(onExecute)
        handlers.append(onExecute)

        onInputChanged = CutlistCommandInputChangedHandler()
        cmd.inputChanged.add(onInputChanged)
        handlers.append(onInputChanged)


class CutlistCommandInputChangedHandler(adsk.core.InputChangedEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        eventArgs = adsk.core.InputChangedEventArgs.cast(args)

        changedInput = eventArgs.input
        if changedInput.id == 'group_dimensions':
            inputs = eventArgs.firingEvent.sender.commandInputs
            materialInput = inputs.itemById('group_material')
            materialInput.isEnabled = changedInput.value


class CutlistCommandExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()

    @report_errors
    def notify(self, args):
        eventArgs = adsk.core.CommandEventArgs.cast(args)
        inputs = eventArgs.command.commandInputs

        app = adsk.core.Application.get()
        ui = app.userInterface
        doc = app.activeDocument
        design = adsk.fusion.Design.cast(app.activeProduct)

        set_preferences_from_inputs(inputs)

        if preferences['tolerance'] > 0:
            Dimensions.tolerance = preferences['tolerance']

        cutlist = CutList(
            preferences['groupBy'],
            ignorehidden=preferences['ignoreHidden'],
            ignoreexternal=preferences['ignoreExternal'],
            axisaligned=preferences['axisAligned'],
        )

        selectionInput = inputs.itemById('selection')
        for i in range(selectionInput.selectionCount):
            cutlist.add(selectionInput.selection(i).entity)

        fmt_class = get_format(preferences['format'])
        fmt = fmt_class(design.unitsManager, doc.name)

        dlg = ui.createFileDialog()
        dlg.title = 'Save Cutlist'
        dlg.filter = fmt.filefilter.filter_str
        dlg.initialFilename = fmt.filename
        if dlg.showSave() != adsk.core.DialogResults.DialogOK:
            return

        filename = dlg.filename
        newline = '' if isinstance(fmt, CSVFormat) else None
        with io.open(filename, 'w', newline=newline, encoding="utf-8") as f:
            f.write(fmt.format(cutlist))

        ui.messageBox(f'Export complete: {filename}', COMMAND_NAME)


def set_preferences_from_inputs(inputs: adsk.core.CommandInputs):
    hiddenInput: adsk.core.BoolValueCommandInput = inputs.itemById('hidden')
    externalInput: adsk.core.BoolValueCommandInput = inputs.itemById('external')
    formatInput: adsk.core.DropDownCommandInput = inputs.itemById('format')
    axisAlignedInput: adsk.core.BoolValueCommandInput = inputs.itemById('axisaligned')
    toleranceInput: adsk.core.ValueCommandInput = inputs.itemById('tolerance')

    dimensionsInput: adsk.core.BoolValueCommandInput = inputs.itemById('group_dimensions')
    materialInput: adsk.core.BoolValueCommandInput = inputs.itemById('group_material')
    group = GroupBy(dimensions=dimensionsInput.value, material=materialInput.value)

    preferences['ignoreHidden'] = hiddenInput.value
    preferences['ignoreExternal'] = externalInput.value
    preferences['groupBy'] = group
    preferences['format'] = formatInput.selectedItem.name
    preferences['axisAligned'] = axisAlignedInput.value
    preferences['tolerance'] = toleranceInput.value


@report_errors
def run(context):
    app = adsk.core.Application.get()
    ui = app.userInterface

    cmdDef = ui.commandDefinitions.addButtonDefinition(
        COMMAND_ID, COMMAND_NAME,
        'Export a cutlist file for the bodies in selected components',
        './/resources')

    onCreate = CutlistCommandCreatedEventHandler()
    cmdDef.commandCreated.add(onCreate)
    handlers.append(onCreate)

    makePanel = ui.allToolbarPanels.itemById('MakePanel')
    makePanel.controls.addCommand(cmdDef)


@report_errors
def stop(context):
    app = adsk.core.Application.get()
    ui = app.userInterface

    cmdDef = ui.commandDefinitions.itemById(COMMAND_ID)
    if cmdDef:
        cmdDef.deleteMe()

    makePanel = ui.allToolbarPanels.itemById('MakePanel')
    button = makePanel.controls.itemById(COMMAND_ID)
    if button:
        button.deleteMe()
