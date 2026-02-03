"""
CTW Analysis Constants

Centralized configuration for event types, colors, and other constants.
"""

# Event type mapping
EVENT_TYPES = {
    0: "MATCH_START",
    1: "MATCH_END",
    2: "SPAWN",
    3: "KILL",
    4: "DEATH",
    5: "POSITION",
    6: "WOOL_TOUCH",
    7: "WOOL_CAPTURE"
}

# Reverse mapping for convenience
EVENT_IDS = {v: k for k, v in EVENT_TYPES.items()}

# Team colors (for visualization)
TEAM_COLORS = {
    'red': '#E74C3C',      # Red team
    'blue': '#3498DB',     # Blue team
    'unknown': '#95A5A6'   # Unassigned/spectators
}

# Event marker styles for matplotlib
EVENT_MARKERS = {
    'spawn': {
        'marker': '^',
        'size': 100,
        'color': 'green',
        'edgecolor': 'black',
        'linewidth': 1.5
    },
    'death': {
        'marker': 'x',
        'size': 100,
        'color': 'red',
        'linewidth': 2
    },
    'kill': {
        'marker': '+',
        'size': 120,
        'color': 'darkred',
        'linewidth': 2.5
    },
    'wool_touch': {
        'marker': '*',
        'size': 150,
        'color': 'yellow',
        'edgecolor': 'black',
        'linewidth': 1.5
    },
    'wool_capture': {
        'marker': '*',
        'size': 200,
        'color': 'gold',
        'edgecolor': 'black',
        'linewidth': 2
    }
}

# Spawn clustering parameters
SPAWN_CLUSTER_RADIUS = 5.0  # Maximum distance (in blocks) to group spawns as same team
MIN_CLUSTER_SIZE = 2        # Minimum spawns to form a valid team cluster

# Map rendering settings
MAP_TILE_SIZE = 1.0
MAP_TILE_COLOR = 'gray'
MAP_TILE_ALPHA = 0.3
MAP_TILE_EDGE_COLOR = 'black'
MAP_TILE_EDGE_WIDTH = 0.3

# Visualization defaults
DEFAULT_MAP_PADDING = 5  # Extra space around map bounds
DEFAULT_LINE_WIDTH = 2
DEFAULT_LINE_ALPHA = 0.6
DEFAULT_MARKER_SIZE = 3
