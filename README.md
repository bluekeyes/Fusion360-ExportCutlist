<img src="./resources/icon.svg" height="64" align="left" />

# Fusion360 Export Cutlist 

An Autodesk Fusion360 addin that can export a cut list of parts in a variety
of formats. It is meant to adapt to multiple workflows and does not require
you to structure your design in a specific way.

## Features

- Operates on bodies, selected either directly or by selecting components
- Exports to JSON, CSV, or text table
- Automatically groups parts by matching body bounding box dimensions and
  materials
  - The largest dimension is considered `length`, the next largest `width`,
    and the smallest `height`
  - Material matching can be disabled if desired
- Additional filtering options for bodies (e.g. visibility)

## Installation

1. Download the latest release
2. Unzip the file on your computer
3. Start Fusion360 and open the "Scripts & Addins" dialog (Shift+S)
4. Go to the "Addins" tab
5. Click the green "+" sign and browse to the folder where you extracted the addin

## License

MIT

## Contributing

Pull requests or issues suggesting additional features or output formats are
welcome. If reporting a bug, please attach or a link to a design that
reproduces the issue.
