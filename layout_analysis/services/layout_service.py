"""Layout extraction orchestration."""

from pathlib import Path

from layout_analysis import (
    RegionReader,
    Y0LayerExtractor,
    TopSurfaceExtractor,
    VerticalDensityExtractor,
    LowestBedrockExtractor,
)


def analyze_layout(
    map_folder: Path,
    force_rerun: bool = False,
    output_dir: Path = None,
    skip_y0: bool = False,
    skip_surface: bool = False,
    skip_density: bool = False,
    skip_bedrock: bool = False,
    threshold: int = 10,
    density_mode: str = 'run',
):
    """
    Step 1: Extract layout data from world folder.

    Args:
        map_folder: Path to map folder (read-only input).
        force_rerun: If True, regenerate even if parquet files exist.
        output_dir: Where to write parquet files (default: map_folder).
        skip_y0: Skip Y=0 layer extraction.
        skip_surface: Skip top surface extraction.
        skip_density: Skip vertical density extraction.
        skip_bedrock: Skip bedrock extraction.
        threshold: Density threshold for vertical density extractor.
        density_mode: Mode for vertical density extractor ('run' or 'count').

    Returns:
        dict: Paths to generated parquet files
    """
    out = Path(output_dir) if output_dir else map_folder
    out.mkdir(parents=True, exist_ok=True)

    print(f"\n[1/4] Layout Analysis: {map_folder.name}")
    print("=" * 70)

    # Define output paths for enabled extractors only
    parquet_files = {}
    if not skip_y0:
        parquet_files['y0_layer'] = out / 'layout_y0.parquet'
    if not skip_surface:
        parquet_files['top_surface'] = out / 'layout_top_surface.parquet'
    if not skip_density:
        parquet_files['vertical_density'] = out / 'layout_vertical_density.parquet'
    if not skip_bedrock:
        parquet_files['bedrock'] = out / 'layout_bedrock.parquet'

    if not parquet_files:
        print("  All extractors skipped.")
        return parquet_files

    # Check if files already exist
    all_exist = all(p.exists() for p in parquet_files.values())
    if all_exist and not force_rerun:
        print("  Layout files already exist. Skipping extraction.")
        for name, path in parquet_files.items():
            print(f"    [OK] {path.name}")
        return parquet_files

    # Find region folder
    region_folder = map_folder / 'region'
    if not region_folder.exists():
        print(f"  [X] No region folder found at {region_folder}")
        return None

    print(f"  Extracting layout from: {region_folder}")

    # Initialize reader
    reader = RegionReader(str(region_folder))

    # Extract Y=0 layer
    if 'y0_layer' in parquet_files:
        if not parquet_files['y0_layer'].exists() or force_rerun:
            print("  Extracting Y=0 layer...")
            extractor = Y0LayerExtractor(reader)
            df = extractor.extract()
            df.to_parquet(parquet_files['y0_layer'])
            print(f"    [OK] Saved {parquet_files['y0_layer'].name} ({len(df)} blocks)")

    # Extract top surface
    if 'top_surface' in parquet_files:
        if not parquet_files['top_surface'].exists() or force_rerun:
            print("  Extracting top surface...")
            extractor = TopSurfaceExtractor(reader)
            df = extractor.extract()
            df.to_parquet(parquet_files['top_surface'])
            print(f"    [OK] Saved {parquet_files['top_surface'].name} ({len(df)} blocks)")

    # Extract vertical density
    if 'vertical_density' in parquet_files:
        if not parquet_files['vertical_density'].exists() or force_rerun:
            print(f"  Extracting vertical density (mode={density_mode}, threshold={threshold})...")
            extractor = VerticalDensityExtractor(reader, threshold=threshold, mode=density_mode)
            df = extractor.extract()
            df.to_parquet(parquet_files['vertical_density'])
            print(f"    [OK] Saved {parquet_files['vertical_density'].name} ({len(df)} columns)")

    # Extract bedrock
    if 'bedrock' in parquet_files:
        if not parquet_files['bedrock'].exists() or force_rerun:
            print("  Extracting lowest bedrock...")
            extractor = LowestBedrockExtractor(reader)
            df = extractor.extract()
            df.to_parquet(parquet_files['bedrock'])
            print(f"    [OK] Saved {parquet_files['bedrock'].name} ({len(df)} blocks)")

    return parquet_files
