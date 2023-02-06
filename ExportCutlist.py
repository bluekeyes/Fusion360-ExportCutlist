#Author-Billy Keyes
#Description-Export a cut list of all bodies as a JSON file

import csv
import functools
import io
import json
import traceback

from operator import attrgetter

import adsk.core
import adsk.fusion

from .lib.texttable import Texttable
from .lib.geometry.bodies import MinimalBody, get_minimal_body


COMMAND_ID = 'ExportCutlistCommand'
COMMAND_NAME = 'Export Cutlist'

DEFAULT_TOLERANCE = 1e-04


# required to keep handlers in scope
handlers = []

# remember user options in between creations of the command
preferences = {
    'ignoreHidden': True,
    'ignoreExternal': False,
    'ignoreMaterial': False,
    'format': 'table',
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

    def matches(self, other, ignorematerial=False):
        if isinstance(other, CutListItem):
            return self.dimensions == other.dimensions and (ignorematerial or self.material == other.material)
        elif isinstance(other, MinimalBody):
            return self.dimensions == Dimensions.from_body(other) and (ignorematerial or self.material == other.material.name)
        else:
            return False

    def add_instance(self, name):
        self.names.append(name)


class CutList:
    def __init__(self, ignorehidden=False, ignorematerial=False, ignoreexternal=False, axisaligned=False, namesep='/'):
        self.items = []
        self.ignorehidden = ignorehidden
        self.ignorematerial = ignorematerial
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
            if item.matches(minimal_body, ignorematerial=self.ignorematerial):
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


class Formatter:
    def __init__(self, unitsMgr: adsk.core.UnitsManager, units=None):
        self.unitsMgr = unitsMgr
        self.units = units if units else unitsMgr.defaultLengthUnits

    def format_value(self, value, showunits=False):
        return self.unitsMgr.formatInternalValue(value, self.units, showunits)

    def cutlist(self, cutlist, fmt='json'):
        fmt = fmt.lower()
        if fmt == 'json':
            return self._cutlistjson(cutlist)
        elif fmt == 'csv':
            return self._cutlistcsv(cutlist)
        elif fmt == 'table':
            return self._cutlisttable(cutlist)
        else:
            raise ValueError(f'unsupported format: {fmt}')

    def _cutlistjson(self, cutlist):
        def todict(item):
            return {
                'count': item.count,
                'dimensions': {
                    'units': self.units,
                    'length': self.format_value(item.dimensions.length),
                    'width': self.format_value(item.dimensions.width),
                    'height': self.format_value(item.dimensions.height),
                },
                'material': item.material,
                'names': item.names,
            }

        return json.dumps([todict(item) for item in cutlist.sorted_items()], indent=2)

    def _cutlistcsv(self, cutlist):
        lengthkey, widthkey, heightkey = [f'{v} ({self.units})' for v in ['length', 'width', 'height']]
        fieldnames = ['count', 'material', lengthkey, widthkey, heightkey, 'names']

        def todict(item):
            return {
                'count': item.count,
                lengthkey: self.format_value(item.dimensions.length),
                widthkey: self.format_value(item.dimensions.width),
                heightkey: self.format_value(item.dimensions.height),
                'material': item.material,
                'names': ','.join(item.names),
            }

        with io.StringIO(newline='') as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows([todict(item) for item in cutlist.sorted_items()])
            return f.getvalue()

    def _cutlisttable(self, cutlist):
        lengthkey, widthkey, heightkey = [f'{v} ({self.units})' for v in ['length', 'width', 'height']]
        fieldnames = ['count', 'material', lengthkey, widthkey, heightkey, 'names']

        def torow(item):
            return [
                item.count,
                item.material,
                self.format_value(item.dimensions.length),
                self.format_value(item.dimensions.width),
                self.format_value(item.dimensions.height),
                '\n'.join(item.names),
            ]

        tt = Texttable(max_width=0)
        tt.set_deco(Texttable.HEADER | Texttable.HLINES)
        tt.header(fieldnames)
        tt.set_cols_dtype(['i', 't', 't', 't', 't', 't'])
        tt.set_cols_align(['r', 'l', 'r', 'r', 'r', 'l'])
        tt.add_rows([torow(item) for item in cutlist.sorted_items()], header=False)
        return tt.draw()


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

        materialInput = inputs.addBoolValueInput('material', 'Ignore materials', True, '', preferences['ignoreMaterial'])
        materialInput.tooltip = 'If checked, bodies with different materials will match if they have the same dimensions.'

        formatInput = inputs.addDropDownCommandInput('format', 'Output Format', adsk.core.DropDownStyles.LabeledIconDropDownStyle)
        formatInput.tooltip = 'The output format of the cutlist.'
        formatInput.listItems.add('Table', preferences['format'] == 'table', '')
        formatInput.listItems.add('JSON', preferences['format'] == 'json', '')
        formatInput.listItems.add('CSV', preferences['format'] == 'csv', '')

        advancedGroup = inputs.addGroupCommandInput('advanced', 'Advanced Options')
        advancedGroup.isEnabledCheckBoxDisplayed = False
        advancedGroup.isExpanded = False

        axisAlignedInput = advancedGroup.children.addBoolValueInput('axisaligned', 'Use axis-aligned boxes', True, '', preferences['axisAligned'])
        axisAlignedInput.tooltip = 'If checked, use axis-algined bounding boxes.'
        axisAlignedInput.tooltipDescription = 'This disables the rotation heuristic and assumes parts are already in the ideal orientation relative to the X, Y, and Z.'

        toleranceInput = advancedGroup.children.addValueInput('tolerance', 'Tolerance', 'mm', adsk.core.ValueInput.createByReal(preferences['tolerance']))
        toleranceInput.tooltip = 'The tolerance used when matching bounding box dimensions.'

        onExecute = CutlistCommandExecuteHandler()
        cmd.execute.add(onExecute)
        handlers.append(onExecute)


class CutlistCommandExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()

    @report_errors
    def notify(self, args):
        eventArgs = adsk.core.CommandEventArgs.cast(args)
        inputs = eventArgs.command.commandInputs

        app = adsk.core.Application.get()
        ui = app.userInterface
        design = adsk.fusion.Design.cast(app.activeProduct)

        set_preferences_from_inputs(inputs)

        if preferences['tolerance'] > 0:
            Dimensions.tolerance = preferences['tolerance']

        cutlist = CutList(
            ignorehidden=preferences['ignoreHidden'],
            ignorematerial=preferences['ignoreMaterial'],
            ignoreexternal=preferences['ignoreExternal'],
            axisaligned=preferences['axisAligned'],
        )

        selectionInput = inputs.itemById('selection')
        for i in range(selectionInput.selectionCount):
            cutlist.add(selectionInput.selection(i).entity)

        newline = None
        fmt = preferences['format']
        if fmt == 'json':
            filefilter = 'JSON Files (*.json)'
        elif fmt == 'csv':
            filefilter = 'CSV Files (*.csv)'
            newline = ''
        else:
            filefilter = 'Text Files (*.txt)'

        dlg = ui.createFileDialog()
        dlg.title = 'Save Cutlist'
        dlg.filter = filefilter
        if dlg.showSave() != adsk.core.DialogResults.DialogOK:
            return

        filename = dlg.filename
        with io.open(filename, 'w', newline=newline) as f:
            formatter = Formatter(design.unitsManager)
            f.write(formatter.cutlist(cutlist, fmt=fmt))

        ui.messageBox(f'Export complete: {filename}', COMMAND_NAME)


def set_preferences_from_inputs(inputs: adsk.core.CommandInputs):
    hiddenInput: adsk.core.BoolValueCommandInput = inputs.itemById('hidden')
    externalInput: adsk.core.BoolValueCommandInput = inputs.itemById('external')
    materialInput: adsk.core.BoolValueCommandInput = inputs.itemById('material')
    formatInput: adsk.core.DropDownCommandInput = inputs.itemById('format')
    axisAlignedInput: adsk.core.BoolValueCommandInput = inputs.itemById('axisaligned')
    toleranceInput: adsk.core.ValueCommandInput = inputs.itemById('tolerance')

    preferences['ignoreHidden'] = hiddenInput.value
    preferences['ignoreExternal'] = externalInput.value
    preferences['ignoreMaterial'] = materialInput.value
    preferences['format'] = formatInput.selectedItem.name.lower()
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
