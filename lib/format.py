import csv
import html
import io
import json
import re
import textwrap
import typing

from dataclasses import dataclass

import adsk.core

from .texttable import Texttable
from .cutlist import CutList, CutListItem


@dataclass
class FormatOptions:
    """
    Options that affect cutlist formatting.

    Options:
      component_names          use component names instead of body names
      short_names              only use the final body or component name, rather than the full path
      remove_numeric_suffixes  remove common numeric suffixes from names
      unique_names             only output unique names for each item
      include_material         include material in the output if the format supports it
      name_separator           the separator to use when joining name elements
      units                    the units to use for dimensions
    """
    component_names: bool = False
    short_names: bool = False
    remove_numeric_suffixes: bool = False
    unique_names: bool = False
    include_material: bool = True
    name_separator: str = '/'
    units: str = 'auto'


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

    def __init__(self, units_manager: adsk.core.UnitsManager, docname: str, options: FormatOptions):
        self.units_manager = units_manager
        self.docname = docname
        self.options = options
        self.units = options.units if options.units != 'auto' else units_manager.defaultLengthUnits

    @property
    def filename(self) -> str:
        name = self.docname.lower().replace(' ', '_')
        return f'{name}.{self.filefilter.ext}'

    def format_value(self, value, showunits=False) -> str:
        return self.units_manager.formatInternalValue(value, self.units, showunits)

    def format_item_names(self, item: CutListItem) -> list[str]:
        separator = self.options.name_separator

        names = []
        for p in item.paths:
            if self.options.component_names and p.parent_name:
                if self.options.short_names:
                    name = p.parent_name
                else:
                    name = separator.join(p.components)
            else:
                if self.options.short_names:
                    name = p.body_name
                else:
                    name = separator.join((*p.components, p.body_name))

            if self.options.remove_numeric_suffixes:
                name = re.sub(r'(\s+\d+|\s*\(\d+\))$', '', name)

            names.append(name)

        if self.options.unique_names:
            names = set(names)

        return sorted(names)

    def format(self, cutlist: CutList):
        raise NotImplementedError


class JSONFormat(Format):
    name = 'JSON'
    filefilter = FileFilter('JSON Files', 'json')

    def item_to_dict(self, item: CutListItem):
        include_material = self.options.include_material
        return {
            'count': item.count,
            'dimensions': {
                'units': self.units,
                'length': self.format_value(item.dimensions.length),
                'width': self.format_value(item.dimensions.width),
                'height': self.format_value(item.dimensions.height),
            },
            **({'material': item.material} if include_material else {}),
            'names': self.format_item_names(item),
        }

    def format(self, cutlist: CutList):
        return json.dumps([self.item_to_dict(item) for item in cutlist.sorted_items()], indent=2)


class CSVDictBuilder:
    def __init__(self, fields: list[str]):
        self.fields = fields
        self.index = 0
        self.dict = {}

    def set_field(self, value: str):
        if self.index < len(self.fields):
            field = self.fields[self.index]
            self.dict[field] = value
            self.index += 1

    def build(self) -> dict:
        return self.dict


class CSVFormat(Format):
    name = 'CSV'
    filefilter = FileFilter('CSV Files', 'csv')

    dialect = 'excel'

    @property
    def fieldnames(self):
        include_material = self.options.include_material
        lengthkey, widthkey, heightkey = [f'{v} ({self.units})' for v in ['length', 'width', 'height']]
        return [
            'count',
            *(['material'] if include_material else []),
            lengthkey,
            widthkey,
            heightkey,
            'names'
        ]

    def item_to_dict(self, item: CutListItem):
        d = CSVDictBuilder(self.fieldnames)

        d.set_field(item.count)

        if self.options.include_material:
            d.set_field(item.material)

        d.set_field(self.format_value(item.dimensions.length))
        d.set_field(self.format_value(item.dimensions.width))
        d.set_field(self.format_value(item.dimensions.height))
        d.set_field(','.join(self.format_item_names(item)))

        return d.build()


    def format(self, cutlist: CutList):
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
        include_material = self.options.include_material
        return [
            'Length',
            'Width',
            'Qty',
            *(['Material'] if include_material else []),
            'Label',
            'Enabled',
        ]

    def item_to_dict(self, item: CutListItem):
        # CutlistOptimizer uses str.split to 'parse' the fields in each record.
        # Import will fail when fields contain the delimiter. Use semicolon to
        # separate the names and remove all delimiters from str values.

        d = CSVDictBuilder(self.fieldnames)

        d.set_field(self.format_value(item.dimensions.length))
        d.set_field(self.format_value(item.dimensions.width))
        d.set_field(item.count)

        if self.options.include_material:
            d.set_field(item.material.replace(',', ''))

        d.set_field(';'.join(n.replace(',', '') for n in self.format_item_names(item)))

        d.set_field('true')

        return d.build()


class CutlistEvoFormat(CSVFormat):
    '''
    Tab-separated format used by https://cutlistevo.com/
    '''

    name = 'Cutlist Evo'
    filefilter = FileFilter('Text Files', 'txt')

    dialect = 'excel-tab'

    @property
    def fieldnames(self):
        include_material = self.options.include_material
        return [
            'Length',
            'Width',
            'Thickness',
            'Quantity',
            'Rotation',
            'Name',
            *(['Material'] if include_material else []),
            'Banding'
        ]

    def item_to_dict(self, item: CutListItem):
        d = CSVDictBuilder(self.fieldnames)

        d.set_field(self.format_value(item.dimensions.length))
        d.set_field(self.format_value(item.dimensions.width))
        d.set_field(self.format_value(item.dimensions.height))
        d.set_field(item.count)
        d.set_field(','.join(['L'] * item.count))
        d.set_field(','.join(self.format_item_names(item)))

        if self.options.include_material:
            d.set_field(item.material)

        d.set_field(','.join(['N'] * item.count))

        return d.build()


class TableFormat(Format):
    name = 'Table'

    @property
    def fieldnames(self):
        include_material = self.options.include_material
        lengthkey, widthkey, heightkey = [f'{v} ({self.units})' for v in ['length', 'width', 'height']]
        return [
            'count',
            *(['material'] if include_material else []),
            lengthkey,
            widthkey,
            heightkey,
            'names',
        ]

    def item_to_row(self, item: CutListItem):
        include_material = self.options.include_material
        return [
            item.count,
            *([item.material] if include_material else []),
            self.format_value(item.dimensions.length),
            self.format_value(item.dimensions.width),
            self.format_value(item.dimensions.height),
            '\n'.join(self.format_item_names(item)),
        ]

    def format(self, cutlist: CutList):
        include_material = self.options.include_material

        tt = Texttable(max_width=0)
        tt.set_deco(Texttable.HEADER | Texttable.HLINES)
        tt.header(self.fieldnames)
        tt.set_cols_dtype(['i', *(['t'] if include_material else []), 't', 't', 't', 't'])
        tt.set_cols_align(['r', *(['l'] if include_material else []), 'r', 'r', 'r', 'l'])
        tt.add_rows([self.item_to_row(item) for item in cutlist.sorted_items()], header=False)
        return tt.draw()


class HTMLFormat(Format):
    name = 'HTML'
    filefilter = FileFilter('HTML Files', 'html')

    @property
    def fieldnames(self):
        include_material = self.options.include_material
        lengthkey, widthkey, heightkey = [f'{v} ({self.units})' for v in ['Length', 'Width', 'Height']]
        return [
            'Count',
            lengthkey,
            widthkey,
            heightkey,
            *(['Material'] if include_material else []),
            'Names',
        ]

    def item_to_row(self, item: CutListItem):
        include_material = self.options.include_material
        cols = [
            item.count,
            self.format_value(item.dimensions.length),
            self.format_value(item.dimensions.width),
            self.format_value(item.dimensions.height),
            *([html.escape(item.material)] if include_material else []),
            '<br>'.join(html.escape(n) for n in self.format_item_names(item)),
        ]
        return '<tr>' + ''.join(f'<td>{c}</td>' for c in cols) + '</tr>'

    def format(self, cutlist: CutList):
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
