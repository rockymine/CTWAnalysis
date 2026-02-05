# Match Analysis Pipeline

## Workflow

```
parse → index (--history) → list → trace / process
```

### 1. Parse match logs

Extract parquet filenames and map names from a structured text log file:

```bash
ctw matches parse --input match_logs/logs.txt --match-dir match_logs/
```

Produces `match_history.csv` with columns `parquet_file,map_name`.

### 2. Index match files

Index parquet files into the metadata database. Pass `--history` to map each
match to its correct map name from the CSV produced by `parse`:

```bash
ctw matches index --match-dir match_logs/ --history match_logs/match_history.csv
```

- `match_id` is an internal sequential integer (1, 2, 3, …), **not** the ID from the log file.
- `match_file` must be unique — duplicate files are skipped.

### 3. List matches

```bash
ctw matches list --map-name Ingwaz
```

### 4. Analyze or visualize

```bash
ctw matches process <match_id>
ctw matches trace --map Ingwaz --match <match_id> --player ALL --color-mode team
```

## Database

Stored at `match_analysis/metadata.db` (DuckDB). Key tables:

| Table | Purpose |
|-------|---------|
| `matches` | One row per indexed parquet file |
| `life_segments` | Extracted player life segments (after `process`) |
| `processing_log` | Audit trail for processing steps |
