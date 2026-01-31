

# XML Analysis Tool

Analyzes Minecraft map XML configuration files and generates visualizations of map regions, spawns, wool objectives, and build restrictions.

## Features

- **Parse XML Configuration**: Extract teams, spawns, wools, regions, and max build height
- **Region Support**: Handle all region types including:
  - Basic: rectangle, cuboid, circle, cylinder, sphere, block, point
  - Composite: union, negative, complement (with recursive nesting)
- **Smart Categorization**: Automatically identify spawn, wool, and build-related regions using regex patterns
- **Visualization**: Generate 2D plots showing:
  - Team spawn areas (color-coded by team)
  - Wool locations and monuments
  - Wool room regions
  - Build restriction zones
- **Category Plots**: Optional separate plots for each region category

## Installation

No additional dependencies beyond the main project requirements (matplotlib, pandas, numpy).

## Quick Start

```bash
py run_xml_analysis.py --xml map_folders/tumbleweed/map.xml
```

This will:
1. Parse the XML file
2. Extract all map data (teams, spawns, wools, regions)
3. Generate a comprehensive visualization
4. Print a detailed summary

## Output Files

Generated files are saved to `output/` by default:

### JSON Data
- `<mapname>_data.json` - Complete structured data in JSON format containing:
  - Map metadata (name, version, objective, max build height)
  - Teams with all attributes
  - Spawns with regions
  - Wools with locations and monuments
  - All named regions with full geometry
  - Region categories

### Visualizations
- `<mapname>_layout.png` - Main visualization showing all regions and objectives
- `spawn_regions.png` - Spawn-specific regions (with `--category-plots`)
- `wool_regions.png` - Wool-specific regions (with `--category-plots`)
- `build_regions.png` - Build restriction regions (with `--category-plots`)

## Command-Line Options

```bash
py run_xml_analysis.py [OPTIONS]
```

### Required Arguments

- `--xml PATH` - Path to map XML file

### Optional Arguments

- `--output DIR` - Output directory for plots and JSON (default: `output`)
- `--category-plots` - Generate separate plots for each region category
- `--no-summary` - Skip printing text summary
- `--no-json` - Skip generating JSON output

### Examples

Basic analysis:
```bash
py run_xml_analysis.py --xml map_folders/tumbleweed/map.xml
```

With category plots:
```bash
py run_xml_analysis.py --xml map_folders/tumbleweed/map.xml --category-plots
```

Custom output directory:
```bash
py run_xml_analysis.py --xml map_folders/tumbleweed/map.xml --output xml_output
```

Only generate JSON without plots (for data extraction):
```bash
py run_xml_analysis.py --xml map_folders/tumbleweed/map.xml --no-summary
# Then check output/tumbleweed_data.json
```

## Region Types

### Basic Regions

- **Rectangle**: 2D area defined by min/max X,Z coordinates
- **Cuboid**: 3D volume defined by min/max X,Y,Z coordinates
- **Circle**: 2D circular area with center and radius
- **Cylinder**: 3D cylinder with base center, radius, and height
- **Sphere**: 3D sphere with origin and radius
- **Block**: Single block coordinate
- **Point**: Single point coordinate

### Composite Regions

- **Union**: Combination of multiple regions
- **Negative**: Inverted region
- **Complement**: Everything except the specified regions

All composite regions support recursive nesting.

## Region Categorization

Regions are automatically categorized using regex patterns on their IDs:

- **Spawn**: IDs containing "spawn" (case-insensitive)
- **Wool**: IDs containing "wool" (case-insensitive)
- **Build**: IDs containing "build", "height", or "limit" (case-insensitive)
- **Other**: All other regions

## Coordinate Handling

The parser correctly handles:
- Standard numeric coordinates
- Infinity values (`oo`, `-oo`)
- Variable placeholders (treated as 0)

## Testing

Run unit tests:

```bash
py -m unittest discover xml_analysis/tests/ -v
```

Tests cover:
- Region value parsing (numbers, infinity, variables)
- Team parsing
- Spawn parsing
- Wool parsing
- Region parsing (all types)
- Region categorization
- Real map parsing (Tumbleweed)

## Visualization Legend

The plots use color coding to distinguish different elements:

- **Red areas**: Red team spawn/wool regions
- **Blue areas**: Blue team spawn/wool regions
- **Magenta stars**: Wool locations
- **Cyan circles**: Wool monuments
- **Gray areas**: Neutral/other regions

## JSON Output Format

The generated JSON includes complete structured data:

```json
{
  "name": "Tumbleweed",
  "version": "1.1.5",
  "objective": "Capture the enemy's two wools!",
  "max_build_height": 29,
  "teams": [
    {
      "id": "red",
      "name": "Red",
      "color": "dark red",
      "max_players": 35
    }
  ],
  "spawns": [
    {
      "team": "blue",
      "kit": "spawn-kit",
      "yaw": 0.0,
      "region": {
        "type": "cuboid",
        "min_x": -79.0,
        "min_y": 9.0,
        "min_z": -176.0,
        "max_x": -80.0,
        "max_y": 9.0,
        "max_z": -177.0
      }
    }
  ],
  "wools": [...],
  "regions": {...},
  "region_categories": {
    "spawn": ["spawns"],
    "wool": ["wool-rooms"]
  }
}
```

This JSON can be used for:
- Automated testing and validation
- Integration with other tools
- Data analysis and statistics
- Creating expected results for test cases

## API Usage

You can also use the parser, visualizer, and exporter programmatically:

```python
from xml_analysis import MapXMLParser, MapVisualizer, MapDataEncoder

# Parse XML
parser = MapXMLParser('map_folders/tumbleweed/map.xml')
data = parser.parse()

# Print info
print(f"Map: {data.name}")
print(f"Teams: {len(data.teams)}")
print(f"Wools: {len(data.wools)}")
print(f"Regions: {len(data.regions)}")

# Categorize regions
categories = parser.identify_region_categories(data)

# Export to JSON
MapDataEncoder.save_json(data, 'output/map_data.json', categories)

# Or get JSON string
json_str = MapDataEncoder.to_json(data, categories)

# Visualize
visualizer = MapVisualizer(data)
visualizer.plot_all('output/map_layout.png')
visualizer.plot_by_category('output/', categories)
```

## Troubleshooting

### "XML file does not exist"
- Check the path to the XML file
- Ensure you're running from the repository root

### "Failed to parse XML"
- Verify the XML file is valid
- Check for malformed tags or attributes
- Ensure the file follows Minecraft map XML schema

### No regions plotted
- Verify regions have valid coordinates
- Check that region IDs are being parsed correctly
- Use `--category-plots` to see regions by category

## Implementation Structure

```
xml_analysis/
├── __init__.py           # Package exports
├── regions.py            # Region class definitions
├── parser.py             # XML parsing logic
├── visualizer.py         # Plotting and visualization
├── tests/
│   ├── __init__.py
│   └── test_parser.py    # Unit tests
└── README.md             # This file
```

## License

Part of the CTW Analysis Toolkit. For educational and analysis purposes.
