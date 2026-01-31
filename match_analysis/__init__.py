"""
CTW Analysis Package

A modular analysis toolkit for Capture the Wool match data.
"""

from .constants import EVENT_TYPES, EVENT_IDS, TEAM_COLORS, EVENT_MARKERS
from .data_loader import load_map_data, load_match_data, list_available_maps, list_available_matches
from .preprocessing import detect_life_segments, assign_teams, cluster_spawn_points
from .map_renderer import render_map_tiles, setup_map_axes
from .match_visualizer import MatchVisualizer
from .utils import get_map_bounds, calculate_player_stats, export_segments_to_csv, print_match_summary
from .segment_classifier import analyze_map_characteristics, classify_segment, classify_all_segments, MapCharacteristics, SegmentClassification

__all__ = [
    # Constants
    'EVENT_TYPES',
    'EVENT_IDS',
    'TEAM_COLORS',
    'EVENT_MARKERS',
    # Data loading
    'load_map_data',
    'load_match_data',
    'list_available_maps',
    'list_available_matches',
    # Preprocessing
    'detect_life_segments',
    'assign_teams',
    'cluster_spawn_points',
    # Rendering
    'render_map_tiles',
    'setup_map_axes',
    # Visualization
    'MatchVisualizer',
    # Utilities
    'get_map_bounds',
    'calculate_player_stats',
    'export_segments_to_csv',
    'print_match_summary',
]

__version__ = '1.0.0'
