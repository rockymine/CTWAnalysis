"""
CTW Match Analysis

Main script for analyzing Capture the Wool matches with team-based visualization.
"""

from match_analysis import (
    load_map_data,
    load_match_data,
    detect_life_segments,
    assign_teams,
    MatchVisualizer,
    print_match_summary,
    calculate_player_stats
)

# =============================================================================
# USER CONFIGURATION
# =============================================================================

# Map and match files (change these to analyze different matches)
MAP_NAME = 'Tumbleweed'
MATCH_FILE = '2026-01-24_22-24-17_75.parquet'

# Visualization settings
SHOW_KILLS = False        # Display kill events
SHOW_DEATHS = True        # Display death events
SHOW_WOOL_EVENTS = True   # Display wool touch/capture events
COLOR_BY_TEAM = True      # Use team colors for player traces

# =============================================================================
# MAIN ANALYSIS
# =============================================================================

def main():
    """Main analysis pipeline."""
    print("="*60)
    print("CTW MATCH ANALYSIS")
    print("="*60)

    # Load data
    print(f"\n1. Loading data...")
    map_data = load_map_data(MAP_NAME)
    match_data = load_match_data(MATCH_FILE)

    # Detect life segments
    print(f"\n2. Processing match data...")
    life_segments = detect_life_segments(match_data)

    if not life_segments:
        print("Error: No life segments detected. Cannot continue.")
        return

    # Assign teams
    print(f"\n3. Identifying teams...")
    life_segments = assign_teams(life_segments)

    # Print match summary
    print_match_summary(life_segments)

    # Calculate player statistics
    print("Top 10 Players by Kills:")
    print("-" * 60)
    player_stats = calculate_player_stats(life_segments)
    print(player_stats.head(10).to_string(index=False))
    print()

    # Create visualization
    print("4. Creating interactive visualization...")
    viz = MatchVisualizer(
        map_data=map_data,
        life_segments=life_segments,
        show_kills=SHOW_KILLS,
        show_deaths=SHOW_DEATHS,
        show_wool_events=SHOW_WOOL_EVENTS,
        color_by_team=COLOR_BY_TEAM
    )

    print("\nOpening interactive visualization window...")
    print("  - Use checkboxes to toggle event types")
    print("  - Use radio buttons to filter by team")
    print("  - Close window to exit")
    print()

    viz.create_interactive_view(
        title=f"CTW Match - {MAP_NAME} - {MATCH_FILE}"
    )

    print("\nAnalysis complete!")


if __name__ == '__main__':
    main()
