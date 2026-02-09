# CTW Analysis -- Claude Code Notes

## Quick Start

```bash
pip install -r requirements.txt
python ctw.py --help
python ctw.py run --map <map_name>       # requires map_folders/<map_name>/
python -m pytest --ignore=skeleton_analysis/test_pathfinding.py -q
```

## Project Overview

Modular analysis toolkit for Capture the Wool (CTW) Minecraft maps. Extracts
block layouts from `.mca` region files, detects islands, builds skeleton graphs,
parses PGM `map.xml` configs, and analyses match event logs.

## Required Data (not in repo)

The `.gitignore` excludes all runtime data. To run the pipeline you need:

- **`map_folders/<name>/region/*.mca`** -- Minecraft Anvil region files (MC 1.8.9)
- **`map_folders/<name>/map.xml`** -- PGM map configuration XML
- **`match_logs/*.parquet`** -- Match event parquet files (optional, for match analysis)
- **`xml_examples/*.xml`** -- Sample XML files used by some tests (optional)

Without `map_folders/`, every `run`/`layout`/`islands`/`xml` command will fail
with "Map folder not found".

## Running Tests

```bash
# Run all unit tests (skips tests that need map data gracefully)
python -m pytest --ignore=skeleton_analysis/test_pathfinding.py -q

# test_pathfinding.py is a standalone script, not a pytest test:
python -m skeleton_analysis.test_pathfinding
```

**Known issue**: `skeleton_analysis/test_pathfinding.py` has bare function
parameters that pytest mistakes for missing fixtures. Run it standalone or
exclude it from pytest collection.

## Config

`ctw_config.yaml` -- priority: CLI args > config file > defaults.
Match-related paths reference Windows locations and need updating for Linux.
