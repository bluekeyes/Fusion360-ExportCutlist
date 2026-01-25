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

from dataclasses import dataclass, field

import adsk.core
import adsk.fusion

from .lib.format import ALL_FORMATS, TableFormat, CSVFormat, get_format
from .lib.cutlist import GroupBy, CutList, CutListOptions


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
class Options:
    cutlist: CutListOptions = field(default_factory=CutListOptions)
    name_separator: str = '/'
    format: str = TableFormat.name
    unit: str = DEFAULT_UNIT


# Remember user options in between creations of the command
user_options = Options()


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

        hidden_input = inputs.addBoolValueInput('hidden', 'Ignore hidden', True, '', user_options.cutlist.ignore_hidden)
        hidden_input.tooltip = 'If checked, hidden bodies are excluded from the cutlist.'

        external_input = inputs.addBoolValueInput('external', 'Ignore external', True, '', user_options.cutlist.ignore_external)
        external_input.tooltip = 'If checked, external components are excluded from the cutlist.'

        format_input = inputs.addDropDownCommandInput('format', 'Output format', adsk.core.DropDownStyles.LabeledIconDropDownStyle)
        format_input.tooltip = 'The output format of the cutlist.'
        for fmt in ALL_FORMATS:
            format_input.listItems.add(fmt.name, user_options.format == fmt.name, '')

        grouping_group = inputs.addGroupCommandInput('grouping', 'Group By')
        grouping_group.isEnabledCheckBoxDisplayed = False
        grouping_group.isExpanded = True

        dimensions_input = grouping_group.children.addBoolValueInput('group_dimensions', 'Dimensions', True, '', user_options.cutlist.group_by.dimensions)
        dimensions_input.tooltip = 'If checked, group bodies by their dimensions.'

        material_input = grouping_group.children.addBoolValueInput('group_material', 'Material', True, '', user_options.cutlist.group_by.material)
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

        axis_aligned_input = advanced_group.children.addBoolValueInput('axisaligned', 'Use axis-aligned boxes', True, '', user_options.cutlist.axis_aligned)
        axis_aligned_input.tooltip = 'If checked, use axis-algined bounding boxes.'
        axis_aligned_input.tooltipDescription = 'This disables the rotation heuristic and assumes parts are already in the ideal orientation relative to the X, Y, and Z axes.'

        tolerance_input = advanced_group.children.addValueInput('tolerance', 'Tolerance', 'mm', adsk.core.ValueInput.createByReal(user_options.cutlist.tolerance))
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

        cutlist = CutList(user_options.cutlist)

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

    user_options.cutlist.ignore_hidden = hidden_input.value
    user_options.cutlist.ignore_external = external_input.value
    user_options.cutlist.group_by = group_by
    user_options.cutlist.axis_aligned = axis_aligned_input.value
    user_options.cutlist.tolerance = tolerance_input.value
    user_options.format = format_input.selectedItem.name
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
