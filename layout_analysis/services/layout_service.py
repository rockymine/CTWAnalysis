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
):
    """
    Step 1: Extract layout data from world folder.

    Args:
        map_folder: Path to map folder (read-only input).
        force_rerun: If True, regenerate even if parquet files exist.
        output_dir: Where to write parquet files (default: map_folder).

    Returns:
        dict: Paths to generated parquet files
    """
    out = Path(output_dir) if output_dir else map_folder
    out.mkdir(parents=True, exist_ok=True)

    print(f"\n[1/4] Layout Analysis: {map_folder.name}")
    print("=" * 70)

    # Define output paths
    parquet_files = {
        'y0_layer': out / 'layout_y0.parquet',
        'top_surface': out / 'layout_top_surface.parquet',
        'vertical_density': out / 'layout_vertical_density.parquet',
        'bedrock': out / 'layout_bedrock.parquet',
    }

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
    if not parquet_files['y0_layer'].exists() or force_rerun:
        print("  Extracting Y=0 layer...")
        extractor = Y0LayerExtractor(reader)
        df = extractor.extract()
        df.to_parquet(parquet_files['y0_layer'])
        print(f"    [OK] Saved {parquet_files['y0_layer'].name} ({len(df)} blocks)")

    # Extract top surface
    if not parquet_files['top_surface'].exists() or force_rerun:
        print("  Extracting top surface...")
        extractor = TopSurfaceExtractor(reader)
        df = extractor.extract()
        df.to_parquet(parquet_files['top_surface'])
        print(f"    [OK] Saved {parquet_files['top_surface'].name} ({len(df)} blocks)")

    # Extract vertical density
    if not parquet_files['vertical_density'].exists() or force_rerun:
        print("  Extracting vertical density...")
        extractor = VerticalDensityExtractor(reader, threshold=10, mode='run')
        df = extractor.extract()
        df.to_parquet(parquet_files['vertical_density'])
        print(f"    [OK] Saved {parquet_files['vertical_density'].name} ({len(df)} columns)")

    # Extract bedrock
    if not parquet_files['bedrock'].exists() or force_rerun:
        print("  Extracting lowest bedrock...")
        extractor = LowestBedrockExtractor(reader)
        df = extractor.extract()
        df.to_parquet(parquet_files['bedrock'])
        print(f"    [OK] Saved {parquet_files['bedrock'].name} ({len(df)} blocks)")

    return parquet_files
