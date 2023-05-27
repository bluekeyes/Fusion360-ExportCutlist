import csv
import io
import json

import adsk.core

from .texttable import Texttable


class Format:
    def __init__(self, unitsMgr: adsk.core.UnitsManager, units=None):
        self.unitsMgr = unitsMgr
        self.units = units if units else unitsMgr.defaultLengthUnits

    def format_value(self, value, showunits=False):
        return self.unitsMgr.formatInternalValue(value, self.units, showunits)

    def format(self, cutlist):
        raise NotImplementedError


class JSONFormat(Format):
    name = 'JSON'
    filefilter = 'JSON Files (*.json)'

    def item_to_dict(self, item):
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

    def format(self, cutlist):
        return json.dumps([self.item_to_dict(item) for item in cutlist.sorted_items()], indent=2)


class CSVFormat(Format):
    name = 'CSV'
    filefilter = 'CSV Files (*.csv)'

    dialect = 'excel'

    @property
    def fieldnames(self):
        lengthkey, widthkey, heightkey = [f'{v} ({self.units})' for v in ['length', 'width', 'height']]
        return [
            'count',
            'material',
            lengthkey,
            widthkey,
            heightkey,
            'names'
        ]

    def item_to_dict(self, item):
        fields = self.fieldnames
        return {
            fields[0]: item.count,
            fields[1]: self.format_value(item.dimensions.length),
            fields[2]: self.format_value(item.dimensions.width),
            fields[3]: self.format_value(item.dimensions.height),
            fields[4]: item.material,
            fields[5]: ','.join(item.names),
        }

    def format(self, cutlist):
        with io.StringIO(newline='') as f:
            w = csv.DictWriter(f, dialect=self.dialect, fieldnames=self.fieldnames)
            w.writeheader()
            w.writerows([self.item_to_dict(item) for item in cutlist.sorted_items()])
            return f.getvalue()


class CutlistOptimizerFormat(CSVFormat):
    '''
    CSV format used by https://cutlistoptimizer.com/
    '''

    name = 'Cutlist Optimizer'

    @property
    def fieldnames(self):
        return ['Length', 'Width', 'Qty', 'Label', 'Enabled']

    def item_to_dict(self, item):
        fields = self.fieldnames
        return {
            fields[0]: self.format_value(item.dimensions.length),
            fields[1]: self.format_value(item.dimensions.width),
            fields[2]: item.count,
            fields[3]: ','.join(item.names),
            fields[4]: 'true'
        }


class CutlistEvoFormat(CSVFormat):
    '''
    Tab-separated format used by https://cutlistevo.com/
    '''

    name = 'Cutlist Evo'
    filefilter = "Text Files (*.txt)"

    dialect = 'excel-tab'

    @property
    def fieldnames(self):
        return ['Length', 'Width', 'Thickness', 'Quantity', 'Rotation', 'Name', 'Material', 'Banding']

    def item_to_dict(self, item):
        fields = self.fieldnames
        return {
            fields[0]: self.format_value(item.dimensions.length),
            fields[1]: self.format_value(item.dimensions.width),
            fields[2]: self.format_value(item.dimensions.height),
            fields[3]: item.count,
            fields[4]: ','.join(['L'] * item.count),
            fields[5]: ','.join(item.names),
            fields[6]: item.material,
            fields[7]: ','.join(['N'] * item.count),
        }


class TableFormat(Format):
    name = 'Table'
    filefilter = 'Text Files (*.txt)'

    @property
    def fieldnames(self):
        lengthkey, widthkey, heightkey = [f'{v} ({self.units})' for v in ['length', 'width', 'height']]
        return ['count', 'material', lengthkey, widthkey, heightkey, 'names']

    def item_to_row(self, item):
        return [
            item.count,
            item.material,
            self.format_value(item.dimensions.length),
            self.format_value(item.dimensions.width),
            self.format_value(item.dimensions.height),
            '\n'.join(item.names),
        ]

    def format(self, cutlist):
        tt = Texttable(max_width=0)
        tt.set_deco(Texttable.HEADER | Texttable.HLINES)
        tt.header(self.fieldnames)
        tt.set_cols_dtype(['i', 't', 't', 't', 't', 't'])
        tt.set_cols_align(['r', 'l', 'r', 'r', 'r', 'l'])
        tt.add_rows([self.item_to_row(item) for item in cutlist.sorted_items()], header=False)
        return tt.draw()


ALL_FORMATS = [
    TableFormat,
    JSONFormat,
    CSVFormat,
    CutlistOptimizerFormat,
    CutlistEvoFormat,
]


def get_format(name):
    for fmt in ALL_FORMATS:
        if fmt.name == name:
            return fmt
    raise ValueError(f'unknown format: {name}')
