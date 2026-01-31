# Layout Analysis Tool

A specialized tool for analyzing Minecraft Java Edition 1.8.9 world layouts from Anvil format region files. Extracts and visualizes layout patterns for PvP map analysis.

## Features

Provides four extraction modes:

1. **Y0 Layer** - Extracts all non-air blocks at world y=0 (bedrock layer)
2. **Top Surface** - Finds the highest non-air block in each vertical column
3. **Vertical Density** - Filters columns by density metrics:
   - `run` mode: Maximum consecutive run length of non-air blocks
   - `count` mode: Total number of non-air blocks in the column
4. **Lowest Bedrock** - Finds the lowest bedrock block (block_id=7) in each vertical column

Each mode produces:
- CSV data files (and Parquet if available)
- 2D visualization plots (PNG format)

## Installation

Install the required dependency:

```bash
py -m pip install anvil-parser
```

(Other dependencies like matplotlib, pandas, numpy are already in the main requirements.txt)

## Quick Start

Run the analysis on a Minecraft world:

```bash
py run_layout_analysis.py --world map_folders/tumbleweed/region
```

This will:
1. Scan all region files in the specified directory
2. Extract data for all three modes
3. Save CSV/Parquet data files to `output/`
4. Generate PNG visualization plots in `output/`

## Output Files

All files are saved to the `output/` directory:

### Data Files
- `y0_layer_points.csv` - Non-air blocks at y=0 (world_x, world_z, block_id, block_data)
- `top_surface_points.csv` - Highest blocks (world_x, world_z, y, block_id, block_data)
- `density_run_N10_points.csv` - Density run mode results (world_x, world_z, metric)
- `density_count_N10_points.csv` - Density count mode results (world_x, world_z, metric)
- `lowest_bedrock_points.csv` - Lowest bedrock blocks (world_x, world_z, y, block_data)

### Visualization Files
- `y0_layer.png` - 2D scatter plot of Y0 layer
- `top_surface.png` - 2D scatter plot of top surface
- `density_run_N10.png` - Density plot (run mode)
- `density_count_N10.png` - Density plot (count mode)
- `lowest_bedrock.png` - 2D scatter plot of lowest bedrock

## Command-Line Options

```bash
py run_layout_analysis.py [OPTIONS]
```

### Required Arguments

- `--world PATH` - Path to Minecraft world region folder (e.g., `map_folders/tumbleweed/region`)

### Optional Arguments

- `--output DIR` - Output directory for plots and data (default: `output`)
- `--threshold N` - Density threshold (default: `10`)
- `--density-mode MODES` - Comma-separated density modes: `run`, `count` (default: `run,count`)
- `--skip-y0` - Skip Y0 layer extraction
- `--skip-surface` - Skip top surface extraction
- `--skip-density` - Skip density extraction
- `--skip-bedrock` - Skip lowest bedrock extraction

### Examples

Extract only Y0 layer and top surface:
```bash
py run_layout_analysis.py --world map_folders/tumbleweed/region --skip-density --skip-bedrock
```

Extract only bedrock:
```bash
py run_layout_analysis.py --world map_folders/tumbleweed/region --skip-y0 --skip-surface --skip-density
```

Use custom threshold and only run mode:
```bash
py run_layout_analysis.py --world map_folders/tumbleweed/region --threshold 15 --density-mode run
```

Save to custom output directory:
```bash
py run_layout_analysis.py --world map_folders/tumbleweed/region --output my_analysis
```

## Technical Details

### Minecraft 1.8.9 Format

The tool correctly handles Minecraft 1.8.9 Anvil format:
- Numeric block IDs (pre-flattening)
- Region files: `r.<rx>.<rz>.mca` containing 32x32 chunks
- Chunk sections: 16x16x16 block volumes
- NBT structure: `Level.Sections[]` with `Y`, `Blocks`, `Data`, `Add` fields

### Block ID Decoding

Block IDs are decoded using:
- `Blocks` array: Low 8 bits of block ID
- `Add` array (optional): High 4 bits for IDs > 255
- Formula: `id = (Blocks[i] & 0xFF) | (nibble(Add, i) << 8)`

### Index Mapping

Block array indices use the formula: `index = (y * 16 + z) * 16 + x`

Where x, y, z are local coordinates within a section (0-15).

### Memory Efficiency

The tool streams through chunks without loading the entire world into memory, making it suitable for analyzing large worlds.

## Testing

Run the unit tests:

```bash
py -m pytest layout_analysis/tests/
```

Or using unittest:

```bash
py -m unittest discover layout_analysis/tests/
```

Tests cover:
- Nibble extraction
- Block ID decoding with/without Add array
- Block metadata decoding
- Index mapping correctness

## API Usage

You can also use the extractors programmatically:

```python
from layout_analysis import RegionReader, Y0LayerExtractor, TopSurfaceExtractor, LowestBedrockExtractor

# Initialize reader
reader = RegionReader('map_folders/tumbleweed/region')

# Extract Y0 layer
extractor = Y0LayerExtractor(reader)
df = extractor.extract()

# Extract lowest bedrock
bedrock_extractor = LowestBedrockExtractor(reader)
bedrock_df = bedrock_extractor.extract()

# Save results
df.to_csv('y0_blocks.csv', index=False)
bedrock_df.to_csv('bedrock_blocks.csv', index=False)
```

## Troubleshooting

### "Region directory does not exist"
- Ensure the path points to the `region/` folder inside your world directory
- Check that region files (`*.mca`) exist in the directory

### "No points to plot"
- The world may be empty or only contain air blocks
- Try different extraction modes or lower thresholds

### "Failed to read region"
- Region file may be corrupted
- Ensure the world is from Minecraft Java Edition 1.8.9

## Implementation Structure

```
layout_analysis/
├── __init__.py           # Package exports
├── utils.py              # NBT decoding utilities (nibble, block ID, etc.)
├── region_reader.py      # Anvil region file reader
├── extractors.py         # Three extraction mode classes
├── plotting.py           # Visualization functions
├── tests/
│   ├── __init__.py
│   └── test_utils.py     # Unit tests for NBT decoding
└── README.md             # This file
```

## License

Part of the CTW Analysis Toolkit. For educational and analysis purposes.
