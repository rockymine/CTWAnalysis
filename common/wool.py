"""Minecraft wool block game data — damage values and color names.

This module is pure game data with no visualization dependency.
For display colors, pair these names with mc_color() from common.visualization.colors.
"""

# Wool block damage value (0-15) → canonical color name.
# Compound names use underscore form. Damage 8 uses 'silver', the name
# stored in PGM map files (also known as 'light_gray' in modern Minecraft).
WOOL_DAMAGE_TO_COLOR: dict[int, str] = {
    0:  'white',
    1:  'orange',
    2:  'magenta',
    3:  'light_blue',
    4:  'yellow',
    5:  'lime',
    6:  'pink',
    7:  'gray',
    8:  'silver',
    9:  'cyan',
    10: 'purple',
    11: 'blue',
    12: 'brown',
    13: 'green',
    14: 'red',
    15: 'black',
}

# Color name → wool damage value.
# Includes aliases for variant spellings seen in map files and databases.
WOOL_COLOR_TO_DAMAGE: dict[str, int] = {v: k for k, v in WOOL_DAMAGE_TO_COLOR.items()}
WOOL_COLOR_TO_DAMAGE.update({
    'light_gray': 8,   # modern Minecraft name for 'silver'
    'light gray':  8,  # space variant
    'light blue':  3,  # space variant of 'light_blue'
})

# Alias table used by normalize_wool_color.
_WOOL_NAME_ALIASES: dict[str, str] = {
    'light_gray': 'silver',
    'light gray': 'silver',
    'light blue': 'light_blue',
}


def normalize_wool_color(color: str) -> str:
    """Normalize a wool color name to the canonical form used in WOOL_DAMAGE_TO_COLOR.

    Handles spaces, underscores, hyphens, case, and alternate names
    (e.g. 'Light Gray', 'light_gray', 'light gray' → 'silver').
    """
    key = color.strip().lower()
    if key in _WOOL_NAME_ALIASES:
        return _WOOL_NAME_ALIASES[key]
    return key.replace(' ', '_').replace('-', '_')
