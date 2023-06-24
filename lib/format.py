import csv
import html
import io
import json
import textwrap
import typing

import adsk.core

from .texttable import Texttable


class FileFilter:
    def __init__(self, name, ext):
        self.name = name
        self.ext = ext

    @property
    def filter_str(self):
        return f'{self.name} (*.{self.ext})'


class Format:
    name = 'Base Format'
    filefilter = FileFilter('Text Files', 'txt')

    def __init__(self, unitsMgr: adsk.core.UnitsManager, docname: str, units=None):
        self.unitsMgr = unitsMgr
        self.docname = docname
        self.units = units if units else unitsMgr.defaultLengthUnits

    @property
    def filename(self):
        name = self.docname.lower().replace(' ', '_')
        return f'{name}.{self.filefilter.ext}'

    def format_value(self, value, showunits=False):
        return self.unitsMgr.formatInternalValue(value, self.units, showunits)

    def format(self, cutlist):
        raise NotImplementedError


class JSONFormat(Format):
    name = 'JSON'
    filefilter = FileFilter('JSON Files', 'json')

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
    filefilter = FileFilter('CSV Files', 'csv')

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
            fields[1]: item.material,
            fields[2]: self.format_value(item.dimensions.length),
            fields[3]: self.format_value(item.dimensions.width),
            fields[4]: self.format_value(item.dimensions.height),
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
    filefilter = FileFilter('Text Files', 'txt')

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


class HTMLFormat(Format):
    name = 'HTML'
    filefilter = FileFilter('HTML Files', 'html')

    @property
    def fieldnames(self):
        lengthkey, widthkey, heightkey = [f'{v} ({self.units})' for v in ['Length', 'Width', 'Height']]
        return ['Count', lengthkey, widthkey, heightkey, 'Material', 'Names']

    def item_to_row(self, item):
        cols = [
            item.count,
            self.format_value(item.dimensions.length),
            self.format_value(item.dimensions.width),
            self.format_value(item.dimensions.height),
            html.escape(item.material),
            '<br>'.join(html.escape(n) for n in item.names),
        ]
        return '<tr>' + ''.join(f'<td>{c}</td>' for c in cols) + '</tr>'

    def format(self, cutlist):
        title = html.escape(self.docname)
        header = ''.join(f'<th>{html.escape(h)}</th>' for h in self.fieldnames)
        rows = ''.join(self.item_to_row(item) for item in cutlist.sorted_items())

        return textwrap.dedent(f'''\
            <html>
                <title>{title} Cutlist</title>
                <style>
                    table {{
                        border: 1px solid #000;
                        border-collapse: collapse;
                    }}
                    td, th {{
                        border: 1px solid #000;
                        padding: 0.25em 0.5em;
                    }}
                    thead {{
                        background-color: #eee;
                    }}
                </style>
            </html>
            </body>
                <h1>{title} Cutlist</h1>
                <table>
                    <thead>{header}</thead>
                    <tbody>{rows}</tbody>
                </table>
            </body>
        ''')



ALL_FORMATS = [
    TableFormat,
    CSVFormat,
    JSONFormat,
    HTMLFormat,
    CutlistOptimizerFormat,
    CutlistEvoFormat,
]


def get_format(name: str) -> typing.Type[Format]:
    for fmt in ALL_FORMATS:
        if fmt.name == name:
            return fmt
    raise ValueError(f'unknown format: {name}')
