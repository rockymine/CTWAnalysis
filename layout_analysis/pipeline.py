"""Layout extraction pipeline — step 2 of the map analysis pipeline."""

import logging
from pathlib import Path
from typing import Optional

from .extractors import (
    Y0LayerExtractor,
    TopSurfaceExtractor,
    VerticalDensityExtractor,
    LowestBedrockExtractor,
    LowestSolidLayerExtractor,
    VerticalSegmentsExtractor,
)
from .region_reader import RegionReader
from .features import ResourceBlockExtractor, ChestExtractor, TileEntityExtractor
from .map_layout_config import MapLayoutConfig

logger = logging.getLogger('ctw')


def _open_region_reader(map_folder: Path) -> Optional[RegionReader]:
    region_folder = map_folder / 'region'
    if not region_folder.exists():
        logger.warning(f"  No region folder found at {region_folder}")
        return None
    return RegionReader(str(region_folder))


def _extract_features(
    reader: RegionReader,
    parquet_files: dict,
    force_rerun: bool,
) -> None:
    if 'resource_blocks' in parquet_files:
        rb_path = parquet_files['resource_blocks']
        if not rb_path.exists() or force_rerun:
            logger.debug("  Extracting resource blocks...")
            df = ResourceBlockExtractor(reader).extract()
            df.to_parquet(rb_path)
            logger.debug(f"    Saved {rb_path.name} ({len(df)} blocks)")

    if 'chest_contents' in parquet_files:
        cc_path = parquet_files['chest_contents']
        if not cc_path.exists() or force_rerun:
            logger.debug("  Extracting chest contents...")
            df = ChestExtractor(reader).extract()
            df.to_parquet(cc_path)
            unique_chests = df[['world_x', 'world_z', 'y']].drop_duplicates()
            logger.debug(
                f"    Saved {cc_path.name} "
                f"({len(unique_chests)} chests, {len(df)} item slots)"
            )

    if 'tile_entities' in parquet_files:
        te_path = parquet_files['tile_entities']
        if not te_path.exists() or force_rerun:
            logger.debug("  Extracting tile entities...")
            df = TileEntityExtractor(reader).extract()
            df.to_parquet(te_path)
            logger.debug(f"    Saved {te_path.name} ({len(df)} tile entities)")


def analyze_layout(
    map_folder: Path,
    force_rerun: bool = False,
    output_dir: Optional[Path] = None,
    skip_y0: bool = False,
    skip_surface: bool = False,
    skip_density: bool = False,
    skip_bedrock: bool = False,
    skip_lowest_solid: bool = False,
    skip_features: bool = False,
    skip_non_solid: bool = False,
    skip_segments: bool = True,
    threshold: int = 10,
    density_mode: str = 'run',
    map_layout_config: Optional[MapLayoutConfig] = None,
    max_build_height: Optional[int] = None,
) -> Optional[dict]:
    """Step 2: Extract layout data from world folder.

    When *map_layout_config* is provided the extraction is driven by the
    per-map configuration from map_layouts.json:

    * ``layout_y0.parquet`` is always generated (needed for build-region
      detection via block-36 markers).
    * ``layout_decided.parquet`` is generated using the configured layer and
      exclusion list and is used by the island-detection step.  Exception:
      when the configured layer is ``y0`` with no exclusions the y0 file is
      reused directly and no ``layout_decided.parquet`` is written.
    * The generic bedrock, lowest_solid, and top_surface parquet files are
      skipped (those are only useful for exploratory comparison).

    Args:
        map_folder: Path to map folder (read-only input).
        force_rerun: If True, regenerate even if parquet files exist.
        output_dir: Where to write parquet files (default: map_folder).
        skip_y0: Skip Y=0 layer extraction (ignored when map_layout_config is set).
        skip_surface: Skip top surface extraction.
        skip_density: Skip vertical density extraction.
        skip_bedrock: Skip bedrock extraction.
        skip_lowest_solid: Skip lowest-solid-layer extraction.
        skip_features: Skip feature extraction (resource blocks and chests).
        skip_non_solid: When True, pass NON_SOLID_BLOCK_IDS to TopSurfaceExtractor
        skip_segments: When False, generate layout_vertical_segments.parquet with all
            contiguous solid Y-ranges per column.  Default True (opt-in) because the
            full-block scan is expensive.
            so decorative blocks (buttons, redstone wire, dead bushes, tall grass,
            flowers) are excluded from the surface scan.
        threshold: Density threshold for vertical density extractor.
        density_mode: Mode for vertical density extractor ('run' or 'count').
        map_layout_config: Per-map config from map_layouts.json.  When
            provided, drives which layer and exclusions to use.
        max_build_height: Y-level ceiling from map.xml.  When set, the
            TopSurfaceExtractor ignores blocks at y >= this value, preventing
            decorative structures above the playable ceiling from masking the
            genuine navigable terrain.  Supplied by the caller from the XML
            analysis step; defaults to None (no cap).

    Returns:
        dict: Paths to generated parquet files, or None on failure.
    """
    out = Path(output_dir) if output_dir else map_folder
    out.mkdir(parents=True, exist_ok=True)

    logger.debug(f"[2/5] Layout Analysis: {map_folder.name}")

    if max_build_height is not None:
        logger.debug(f"  Build height cap: y < {max_build_height} (from map.xml)")

    if map_layout_config is not None:
        return _analyze_layout_configured(
            map_folder, out, force_rerun, map_layout_config, skip_features,
            skip_non_solid, max_build_height, skip_segments,
        )

    # -----------------------------------------------------------------------
    # Standard (unconfigured) extraction: respect explicit skip flags
    # -----------------------------------------------------------------------

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
    if not skip_lowest_solid:
        parquet_files['lowest_solid'] = out / 'layout_lowest_solid.parquet'
    if not skip_features:
        parquet_files['resource_blocks'] = out / 'layout_resource_blocks.parquet'
        parquet_files['chest_contents'] = out / 'layout_chest_contents.parquet'
        parquet_files['tile_entities'] = out / 'layout_tile_entities.parquet'
    if not skip_segments:
        parquet_files['vertical_segments'] = out / 'layout_vertical_segments.parquet'

    if not parquet_files:
        logger.debug("  All extractors skipped.")
        return parquet_files

    # Check if files already exist
    all_exist = all(p.exists() for p in parquet_files.values())
    if all_exist and not force_rerun:
        logger.debug("  Layout files already exist. Skipping extraction.")
        for name, path in parquet_files.items():
            logger.debug(f"    {path.name}")
        return parquet_files

    reader = _open_region_reader(map_folder)
    if reader is None:
        return None

    logger.debug(f"  Extracting layout from: {map_folder / 'region'}")

    # Extract Y=0 layer
    if 'y0_layer' in parquet_files:
        if not parquet_files['y0_layer'].exists() or force_rerun:
            logger.debug("  Extracting Y=0 layer...")
            extractor = Y0LayerExtractor(reader)
            df = extractor.extract()
            df.to_parquet(parquet_files['y0_layer'])
            logger.debug(f"    Saved {parquet_files['y0_layer'].name} ({len(df)} blocks)")

    # Extract top surface
    if 'top_surface' in parquet_files:
        if not parquet_files['top_surface'].exists() or force_rerun:
            logger.debug("  Extracting top surface...")
            extractor = TopSurfaceExtractor(
                reader, skip_non_solid=skip_non_solid,
                max_build_height=max_build_height,
            )
            df = extractor.extract()
            df.to_parquet(parquet_files['top_surface'])
            logger.debug(f"    Saved {parquet_files['top_surface'].name} ({len(df)} blocks)")

    # Extract vertical density
    if 'vertical_density' in parquet_files:
        if not parquet_files['vertical_density'].exists() or force_rerun:
            logger.debug(f"  Extracting vertical density (mode={density_mode}, threshold={threshold})...")
            extractor = VerticalDensityExtractor(reader, threshold=threshold, mode=density_mode)
            df = extractor.extract()
            df.to_parquet(parquet_files['vertical_density'])
            logger.debug(f"    Saved {parquet_files['vertical_density'].name} ({len(df)} columns)")

    # Extract bedrock
    if 'bedrock' in parquet_files:
        if not parquet_files['bedrock'].exists() or force_rerun:
            logger.debug("  Extracting lowest bedrock...")
            extractor = LowestBedrockExtractor(reader)
            df = extractor.extract()
            df.to_parquet(parquet_files['bedrock'])
            logger.debug(f"    Saved {parquet_files['bedrock'].name} ({len(df)} blocks)")

    # Extract lowest solid layer (first non-air, non-void block from below)
    if 'lowest_solid' in parquet_files:
        if not parquet_files['lowest_solid'].exists() or force_rerun:
            logger.debug("  Extracting lowest solid layer...")
            extractor = LowestSolidLayerExtractor(reader)
            df = extractor.extract()
            df.to_parquet(parquet_files['lowest_solid'])
            logger.debug(f"    Saved {parquet_files['lowest_solid'].name} ({len(df)} blocks)")

    # Extract vertical segments (all contiguous solid Y-runs per column)
    if 'vertical_segments' in parquet_files:
        if not parquet_files['vertical_segments'].exists() or force_rerun:
            logger.debug("  Extracting vertical segments...")
            extractor = VerticalSegmentsExtractor(reader, skip_non_solid=skip_non_solid)
            df = extractor.extract()
            df.to_parquet(parquet_files['vertical_segments'])
            logger.debug(
                f"    Saved {parquet_files['vertical_segments'].name} ({len(df)} runs)"
            )

    _extract_features(reader, parquet_files, force_rerun)
    return parquet_files


def _analyze_layout_configured(
    map_folder: Path,
    out: Path,
    force_rerun: bool,
    cfg: MapLayoutConfig,
    skip_features: bool,
    skip_non_solid: bool = False,
    max_build_height: Optional[int] = None,
    skip_segments: bool = True,
) -> Optional[dict]:
    """Configured extraction path driven by map_layouts.json.

    Always produces layout_y0.parquet.  Produces layout_decided.parquet when
    the configured layer is not y0 or when y0 is configured with exclusions.
    Skips the generic bedrock/lowest_solid/top_surface parquets.
    """
    import pandas as pd

    layer = cfg.layer
    exclude = cfg.exclude

    # Determine which files this run is responsible for
    y0_path = out / 'layout_y0.parquet'
    # layout_decided is needed when layer != y0 OR when y0 has exclusions
    need_decided = layer != 'y0' or bool(exclude)
    decided_path = out / 'layout_decided.parquet' if need_decided else None

    top_surface_path = out / 'layout_top_surface.parquet'
    parquet_files: dict[str, Path] = {'y0_layer': y0_path, 'top_surface': top_surface_path}
    if decided_path is not None:
        parquet_files['decided'] = decided_path
    if not skip_features:
        parquet_files['resource_blocks'] = out / 'layout_resource_blocks.parquet'
        parquet_files['chest_contents'] = out / 'layout_chest_contents.parquet'
        parquet_files['tile_entities'] = out / 'layout_tile_entities.parquet'
    if not skip_segments:
        parquet_files['vertical_segments'] = out / 'layout_vertical_segments.parquet'

    all_exist = all(p.exists() for p in parquet_files.values())
    if all_exist and not force_rerun:
        logger.debug("  Layout files already exist. Skipping extraction.")
        for path in parquet_files.values():
            logger.debug(f"    {path.name}")
        return parquet_files

    reader = _open_region_reader(map_folder)
    if reader is None:
        return None

    logger.debug(f"  Extracting layout from: {map_folder / 'region'} (layer={layer}, exclude={exclude})")

    # --- Y=0 layer (always, unfiltered — needed for block-36 build-region detection) ---
    if not y0_path.exists() or force_rerun:
        logger.debug("  Extracting Y=0 layer...")
        df_y0 = Y0LayerExtractor(reader).extract()
        df_y0.to_parquet(y0_path)
        logger.debug(f"    Saved {y0_path.name} ({len(df_y0)} blocks)")
    else:
        df_y0 = None  # already on disk, load only if needed for decided

    # --- Decided layer ---
    if decided_path is not None and (not decided_path.exists() or force_rerun):
        if layer == 'y0':
            # Post-filter: load y0 and remove excluded block IDs
            if df_y0 is None:
                df_y0 = pd.read_parquet(y0_path)
            df_decided = df_y0[~df_y0['block_id'].isin(exclude)].copy()
            df_decided.to_parquet(decided_path)
            logger.debug(
                f"    Saved {decided_path.name} ({len(df_decided)} blocks, "
                f"filtered {len(df_y0) - len(df_decided)} excluded)"
            )
        elif layer == 'lowest_solid':
            # Merge config exclusions with the mandatory block-36 exclusion
            exclude_set = set(exclude) | {36}
            extractor = LowestSolidLayerExtractor(reader, exclude_ids=exclude_set)
            df = extractor.extract()
            df.to_parquet(decided_path)
            logger.debug(f"    Saved {decided_path.name} ({len(df)} blocks)")
        elif layer == 'top_surface':
            extractor = TopSurfaceExtractor(
                reader, exclude_ids=set(exclude), skip_non_solid=skip_non_solid,
                max_build_height=max_build_height,
            )
            df = extractor.extract()
            df.to_parquet(decided_path)
            logger.debug(f"    Saved {decided_path.name} ({len(df)} blocks)")
        elif layer == 'bedrock':
            # Bedrock has no scanning concept; exclusion lists don't apply
            extractor = LowestBedrockExtractor(reader)
            df = extractor.extract()
            df.to_parquet(decided_path)
            logger.debug(f"    Saved {decided_path.name} ({len(df)} blocks)")

    # --- Top surface (needed by populate_terrain_height regardless of configured layer) ---
    if not top_surface_path.exists() or force_rerun:
        logger.debug("  Extracting top surface (capped at build height)...")
        extractor = TopSurfaceExtractor(
            reader, skip_non_solid=skip_non_solid,
            max_build_height=max_build_height,
        )
        df = extractor.extract()
        df.to_parquet(top_surface_path)
        logger.debug(f"    Saved {top_surface_path.name} ({len(df)} blocks)")

    # --- Vertical segments ---
    if 'vertical_segments' in parquet_files:
        vs_path = parquet_files['vertical_segments']
        if not vs_path.exists() or force_rerun:
            logger.debug("  Extracting vertical segments...")
            df = VerticalSegmentsExtractor(reader, skip_non_solid=skip_non_solid).extract()
            df.to_parquet(vs_path)
            logger.debug(f"    Saved {vs_path.name} ({len(df)} runs)")

    # --- Feature extractors ---
    _extract_features(reader, parquet_files, force_rerun)
    return parquet_files
