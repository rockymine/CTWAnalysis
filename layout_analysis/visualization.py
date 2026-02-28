"""
Plotting functions for visualizing extracted layout data.

Provides 2D scatter and pixel-based plots for point sets.
"""

import logging
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
import pandas as pd

logger = logging.getLogger('ctw')


def save_point_plot(
    df: pd.DataFrame,
    output_path: str,
    title: str,
    use_binned: bool | None = None,
    bin_size: int = 1
) -> None:
    """
    Save a 2D plot of world_x vs world_z points.

    Args:
        df: DataFrame with 'world_x' and 'world_z' columns
        output_path: Path to save the plot image
        title: Plot title
        use_binned: If True, use binned/pixel plot. If None, auto-decide based on point count.
        bin_size: Size of bins in blocks (for binned plots)
    """
    if df.empty:
        logger.warning(f"No points to plot for {title}")
        # Create an empty plot
        fig, ax = plt.subplots(figsize=(10, 10))
        ax.text(0.5, 0.5, 'No data points', ha='center', va='center', fontsize=16)
        ax.set_title(title)
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
        return

    x = df['world_x'].values
    z = df['world_z'].values

    # Auto-decide whether to use binned plot
    if use_binned is None:
        use_binned = len(df) > 100000

    # Create figure
    fig, ax = plt.subplots(figsize=(12, 12))

    if use_binned:
        # Binned/pixel plot for large datasets
        x_min, x_max = x.min(), x.max()
        z_min, z_max = z.min(), z.max()

        # Create bins
        x_bins = np.arange(x_min, x_max + bin_size, bin_size)
        z_bins = np.arange(z_min, z_max + bin_size, bin_size)

        # Create 2D histogram
        hist, x_edges, z_edges = np.histogram2d(x, z, bins=[x_bins, z_bins])

        # Plot as image
        extent = [x_edges[0], x_edges[-1], z_edges[0], z_edges[-1]]
        im = ax.imshow(
            hist.T,
            origin='lower',
            extent=extent,
            cmap='viridis',
            aspect='equal',
            interpolation='nearest'
        )
        plt.colorbar(im, ax=ax, label='Point count per bin')

    else:
        # Scatter plot for smaller datasets
        ax.scatter(x, z, s=1, alpha=0.5, c='blue', marker='.')

    # Set labels and title
    ax.set_xlabel('World X', fontsize=12)
    ax.set_ylabel('World Z', fontsize=12)
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.set_aspect('equal')
    ax.invert_yaxis()
    ax.grid(True, alpha=0.3)

    # Save
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()

    logger.debug(f"  Saved plot: {output_path}")


def save_all_plots(
    y0_df: pd.DataFrame,
    top_surface_df: pd.DataFrame,
    density_dfs: dict[str, pd.DataFrame],
    bedrock_df: pd.DataFrame,
    output_dir: str
) -> None:
    """
    Save all plots to the output directory.

    Args:
        y0_df: Y0 layer extraction results
        top_surface_df: Top surface extraction results
        density_dfs: Dictionary mapping mode names to density extraction results
                     e.g., {'run_N10': df, 'count_N10': df}
        bedrock_df: Lowest bedrock extraction results
        output_dir: Directory to save plots
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    logger.debug("Generating plots...")

    # Y0 layer plot
    save_point_plot(
        y0_df,
        str(output_path / 'y0_layer.png'),
        'Y0 Layer - Non-air blocks at world y=0'
    )

    # Top surface plot
    save_point_plot(
        top_surface_df,
        str(output_path / 'top_surface.png'),
        'Top Surface - Highest non-air block per column'
    )

    # Density plots
    for mode_name, df in density_dfs.items():
        save_point_plot(
            df,
            str(output_path / f'density_{mode_name}.png'),
            f'Vertical Density - {mode_name.replace("_", " ").title()}'
        )

    # Bedrock plot
    save_point_plot(
        bedrock_df,
        str(output_path / 'lowest_bedrock.png'),
        'Lowest Bedrock - Lowest bedrock block per column'
    )

    logger.debug("All plots saved successfully!")
