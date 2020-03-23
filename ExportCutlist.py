#Author-Billy Keyes
#Description-Export a cut list of all bodies as a JSON file

import csv
import functools
import io
import json

from collections import namedtuple
from operator import attrgetter

import adsk.core, adsk.fusion, traceback

from .lib.texttable import Texttable

COMMAND_ID = 'ExportCutlistCommand'
COMMAND_NAME = 'Export Cutlist'

# required to keep handlers in scope
handlers = []

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
    epsilon = 0.0001

    @classmethod
    def from_body(cls, body):
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
            return (abs(self.length - other.length) < Dimensions.epsilon and
                    abs(self.width - other.width) < Dimensions.epsilon and
                    abs(self.height - other.height) < Dimensions.epsilon)
        return NotImplemented


class CutListItem:
    def __init__(self, body, name, ignorematerial=False):
        self.names = [name]
        self.dimensions = Dimensions.from_body(body)

        self.ignorematerial = ignorematerial
        if ignorematerial:
            self.material = None
        else:
            self.material = body.material.name

    @property
    def count(self):
        return len(self.names)

    def add(self, body, name=None):
        dimensions = Dimensions.from_body(body)
        matches = self.dimensions == dimensions and (self.ignorematerial or self.material == body.material.name)

        if matches:
            self.names.append(name if name else body.name)
            return True
        else:
            return False


class CutList:
    def __init__(self, ignorehidden=False, ignorematerial=False, ignoreexternal=False, namesep='/'):
        self.items = []
        self.ignorehidden = ignorehidden
        self.ignorematerial = ignorematerial
        self.ignoreexternal = ignoreexternal
        self.namesep = namesep

    def addBody(self, body, name):
        if not body.isSolid:
            return

        if not body.isVisible and self.ignorehidden:
            return

        added = False
        for item in self.items:
            if item.add(body, name):
                added = True
                break

        if not added:
            item = CutListItem(body, name, ignorematerial=self.ignorematerial)
            self.items.append(item)

    def add(self, obj, name=None):
        if type(obj) is adsk.fusion.BRepBody:
            self.addBody(obj, self._joinname(name, obj.name))

        elif type(obj) is adsk.fusion.Occurrence:
            if obj.isReferencedComponent and self.ignoreexternal:
                return 
            for body in obj.bRepBodies:
                self.addBody(body, self._joinname(name, obj.component.name, body.name))
            for child in obj.childOccurrences:
                self.add(child, self._joinname(name, obj.component.name))

        elif type(obj) is adsk.fusion.Component:
            for body in obj.bRepBodies:
                self.addBody(body, self._joinname(name, obj.name, body.name))
            for occ in obj.occurrences:
                self.add(occ, self._joinname(name, obj.name))

        else:
            raise ValueError(f'Cannot add object with type: {obj.objectType}')

    def sortedItems(self):
        items = list(self.items)
        items.sort(key=lambda i: attrgetter('length', 'width', 'height')(i.dimensions), reverse=True)
        items.sort(key=attrgetter('count'), reverse=True)
        items.sort(key=attrgetter('material'))
        return items

    def _joinname(self, *parts):
        return self.namesep.join([p for p in parts if p])


class Formatter:
    def __init__(self, unitsMgr, units=None):
        self.unitsMgr = unitsMgr
        self.units = units if units else unitsMgr.defaultLengthUnits

    def value(self, value, showunits=True):
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
                    'length': self.value(item.dimensions.length),
                    'width': self.value(item.dimensions.width),
                    'height': self.value(item.dimensions.height),
                },
                'material': item.material,
                'names': item.names,
            }

        return json.dumps([todict(item) for item in cutlist.sortedItems()], indent=2)

    def _cutlistcsv(self, cutlist):
        lengthkey, widthkey, heightkey = [f'{v} ({self.units})' for v in ['length', 'width', 'height']]
        fieldnames = ['count', 'material', lengthkey, widthkey, heightkey, 'names']

        def todict(item):
            return {
                'count': item.count,
                lengthkey: self.value(item.dimensions.length, False),
                widthkey: self.value(item.dimensions.width, False),
                heightkey: self.value(item.dimensions.height, False),
                'material': item.material,
                'names': ','.join(item.names),
            }

        with io.StringIO(newline='') as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows([todict(item) for item in cutlist.sortedItems()])
            return f.getvalue()

    def _cutlisttable(self, cutlist):
        lengthkey, widthkey, heightkey = [f'{v} ({self.units})' for v in ['length', 'width', 'height']]
        fieldnames = ['count', 'material', lengthkey, widthkey, heightkey, 'names']

        def torow(item):
            return [
                item.count,
                item.material,
                self.value(item.dimensions.length, False),
                self.value(item.dimensions.width, False),
                self.value(item.dimensions.height, False),
                '\n'.join(item.names),
            ]

        tt = Texttable(max_width=0)
        tt.set_deco(Texttable.HEADER | Texttable.HLINES)
        tt.header(fieldnames)
        tt.set_cols_dtype(['i', 't', 't', 't', 't', 't'])
        tt.set_cols_align(['r', 'l', 'r', 'r', 'r', 'l'])
        tt.add_rows([torow(item) for item in cutlist.sortedItems()], header=False)
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

        hiddenInput = inputs.addBoolValueInput('hidden', 'Ignore hidden', True, '', True)
        hiddenInput.tooltip = 'If checked, hidden bodies are excluded from the cutlist.'

        externalInput = inputs.addBoolValueInput('external', 'Ignore external', True, '', False)
        externalInput.tooltip = 'If checked, external components are excluded from the cutlist.'

        materialInput = inputs.addBoolValueInput('material', 'Ignore materials', True, '', False)
        materialInput.tooltip = 'If checked, bodies with different materials will match if they have the same dimensions'

        formatInput = inputs.addDropDownCommandInput('format', 'Output Format', adsk.core.DropDownStyles.LabeledIconDropDownStyle)
        formatInput.tooltip = 'The output format of the cutlist.'
        formatInput.listItems.add('Table', True, '')
        formatInput.listItems.add('JSON', False, '')
        formatInput.listItems.add('CSV', False, '')

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

        hiddenInput = inputs.itemById('hidden')
        externalInput = inputs.itemById('external')
        materialInput = inputs.itemById('material')
        selectionInput = inputs.itemById('selection')
        formatInput = inputs.itemById('format')

        cutlist = CutList(
            ignorehidden=hiddenInput.value,
            ignorematerial=materialInput.value,
            ignoreexternal=externalInput.value,
        )
        for i in range(selectionInput.selectionCount):
            cutlist.add(selectionInput.selection(i).entity)

        newline = None
        fmt = formatInput.selectedItem.name.lower()
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