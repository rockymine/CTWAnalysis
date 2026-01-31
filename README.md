# CTW Analysis Toolkit

A modular analysis toolkit for Capture the Wool (CTW) Minecraft maps and match data. Built with [Claude Code](https://claude.com/claude-code).

## Features

- **Layout Analysis**: Extract and analyze map block layouts from Minecraft region files
- **XML Analysis**: Parse PGM map.xml files to extract spawns, wools, regions, and teams
- **Island Detection**: Identify disconnected landmasses with skeleton graph extraction, D4 canonicalization, and POI annotation
- **Match Analysis**: Process match event logs with life segment detection, team identification, and role classification
- **Visualization**: Generate debug images, skeleton graphs, POI overlays, and match heatmaps

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Populate Map Folders

Each map needs its own folder inside `map_folders/` containing the Minecraft world data:

```
map_folders/
  your_map_name/
    region/           # Minecraft region files (.mca)
    map.xml           # PGM map XML file
```

The `region/` directory should contain the Minecraft world region files (e.g., `r.0.0.mca`). The `map.xml` is the PGM map definition with spawns, wools, and regions.

### 3. Populate Match Logs

Place match event parquet files into `match_logs/`:

```
match_logs/
  2026-01-24_09-26-48_3.parquet
  2026-01-24_10-42-00_15.parquet
  ...
```

Each parquet file contains event data for a single match with columns: `timestamp`, `event_type`, `player_id`, `x`, `y`, `z`, `held_item`, `inventory_count`, `wool_id`.

## Running the Analysis

### Unified Workflow

The recommended way to run all analysis steps:

```bash
python run_analysis_workflow.py --map your_map_name
```

This runs in order:
1. **Layout Analysis** -- extracts block coordinates from region files into parquet files
2. **Island Analysis** -- detects islands, computes skeleton graphs, annotates POIs from XML
3. **XML Analysis** -- parses map.xml into structured JSON
4. **Match Analysis** -- processes match logs with map context

Use flags to skip steps:
```bash
python run_analysis_workflow.py --map your_map_name --no-layout    # skip layout extraction
python run_analysis_workflow.py --map your_map_name --no-xml       # skip XML parsing
python run_analysis_workflow.py --map your_map_name --no-matches   # skip match analysis
python run_analysis_workflow.py --map your_map_name --force        # re-run even if outputs exist
```

### Individual Scripts

```bash
python run_layout_analysis.py --map your_map_name    # layout extraction only
python run_xml_analysis.py --map your_map_name        # XML parsing only
python generate_plots.py                              # match visualization (uses config.json)
python classify_segments.py                           # life segment classification
```

## Output Structure

After running the workflow, each map folder will contain:

```
map_folders/your_map_name/
  region/                          # (input) Minecraft region files
  map.xml                          # (input) PGM map definition
  layout_bedrock.parquet           # extracted block coordinates
  layout_top_surface.parquet       # top surface layer
  map_data.json                    # parsed XML data
  island_analysis/
    map_context.json               # aggregated map context (islands, POIs, skeleton stats)
    island_comparison.png          # island overview
    island_statistics.png          # size/shape statistics
    island_report.txt              # text report
    skeleton/
      world_overview.png           # skeleton graph on world layout
      unique_islands.png           # canonical shape comparison
      island_N_debug.png           # per-island skeleton debug
      island_N_poi.png             # per-island POI annotation
      exports/                     # JSON exports of skeleton graphs
```

## Configuration

Edit `config.json` for match visualization settings:

```json
{
  "data_files": {
    "map_name": "Tumbleweed",
    "match_file": "2026-01-24_22-24-17_75.parquet"
  },
  "output": { "folder": "output", "dpi": 150, "generate_pdf": true },
  "team_settings": { "all_teams": true, "red_team": true, "blue_team": true },
  "role_settings": { "wool_runner": true, "rusher": true, ... }
}
```

## Data Format

### Match Data (Parquet)

| Column | Description |
|--------|-------------|
| `timestamp` | Event time |
| `event_type` | 0=MATCH_START, 1=MATCH_END, 2=SPAWN, 3=KILL, 4=DEATH, 5=POSITION, 6=WOOL_TOUCH, 7=WOOL_CAPTURE |
| `player_id` | Player identifier |
| `x`, `y`, `z` | World coordinates |
| `held_item` | Currently held item |
| `inventory_count` | Inventory item count |
| `wool_id` | Wool identifier (for wool events) |

## Project Structure

```
CTWAnalysisWithClaudeCode/
├── layout_analysis/              # Layout and island analysis package
│   ├── islands/                  # Island detection, triangulation, statistics
│   ├── skeleton/                 # Skeleton graph extraction and POI annotation
│   │   ├── pipeline.py           # Full skeleton pipeline orchestrator
│   │   ├── canonicalize.py       # D4 dihedral group canonicalization
│   │   ├── skeletonize.py        # Morphological thinning
│   │   ├── nodes.py              # Endpoint/junction extraction
│   │   ├── edges.py              # Edge walking
│   │   ├── merge.py              # Junction blob merging
│   │   ├── prune.py              # Short branch pruning
│   │   ├── poi_annotation.py     # Spawn/wool POI classification
│   │   └── visualize.py          # Skeleton and POI visualization
│   └── map_context.py            # MapContext aggregation
├── xml_analysis/                 # PGM XML parsing
│   ├── parser.py                 # Map XML parser
│   ├── regions.py                # Region type hierarchy
│   └── exporter.py               # JSON export
├── match_analysis/               # Match event processing
│   ├── preprocessing.py          # Life segments and team detection
│   ├── segment_classifier.py     # Role classification
│   ├── match_visualizer.py       # Visualization
│   └── pdf_report.py             # PDF report generation
├── map_folders/                  # Map data (not tracked in git)
├── match_logs/                   # Match parquet files (not tracked in git)
├── run_analysis_workflow.py      # Unified workflow script
├── config.json                   # Match visualization config
└── requirements.txt              # Python dependencies
```

## License

This project is for educational and analysis purposes.
