"""Shared color constants for CTW visualizations."""

# Background color used by dark-theme traffic/graph visualizations
DARK_THEME_BG = "#0d0d18"


def mc_color_key(name: str) -> str:
    """Normalize a Minecraft color name to canonical underscore_lowercase form.

    Handles the three common variant forms used across the codebase:
      "light blue", "light-blue", "light_blue" → "light_blue"
    """
    return name.strip().lower().replace(' ', '_').replace('-', '_')


# Unified Minecraft color registry covering all chat-format and wool/dye names.
# Canonical keys use underscore_lowercase form; call mc_color() for normalized lookup.
#
# For the 7 names present in both chat and wool palettes (red, blue, green,
# yellow, white, gray, black) the chat-format hex values are used — they are
# brighter and more legible in all visualization contexts.
#
# Wool-specific names (orange, cyan, magenta, purple, light_blue, lime, pink,
# silver/light_gray, brown) use their authentic Minecraft dye hex values.
MINECRAFT_COLORS: dict[str, str] = {
    # Chat-format colors (appear in map_context.json teams[].color)
    'dark_red':     '#AA0000',
    'red':          '#FF5555',
    'gold':         '#FFAA00',
    'yellow':       '#DDDD00',
    'dark_green':   '#00AA00',
    'green':        '#55FF55',
    'aqua':         '#55FFFF',
    'dark_aqua':    '#00AAAA',
    'dark_blue':    '#0000AA',
    'blue':         '#5555FF',
    'light_purple': '#FF55FF',
    'dark_purple':  '#AA00AA',
    'white':        '#FFFFFF',
    'gray':         '#AAAAAA',
    'dark_gray':    '#555555',
    'black':        '#000000',
    # Wool/dye-specific names (appear in poi_assignments spawns[].team_color)
    'orange':       '#f07613',
    'magenta':      '#bd44b3',
    'light_blue':   '#3aafd9',
    'lime':         '#70b919',
    'pink':         '#ed8dac',
    'silver':       '#8e8e86',   # light gray wool
    'light_gray':   '#8e8e86',   # alias for silver
    'cyan':         '#158991',
    'purple':       '#792aac',
    'brown':        '#724728',
}


def mc_color(name: str, default: str = '#888888') -> str:
    """Look up a Minecraft color by name, normalizing space/hyphen/case variants.

    >>> mc_color('light blue')
    '#3aafd9'
    >>> mc_color('Dark_Red')
    '#AA0000'
    >>> mc_color('unknown', '#ff0000')
    '#ff0000'
    """
    return MINECRAFT_COLORS.get(mc_color_key(name), default)


# Fallback color for islands with no team assignment (neutral/observer islands)
NEUTRAL_COLOR = '#6b7280'


def distance_to_rgba(dist: float, max_dist: float) -> tuple[float, float, float, float]:
    """Map a distance to a green→yellow→red RGBA gradient.

    Returns an (r, g, b, a) tuple with components in [0, 1].
    dist=0 is full green; dist=max_dist is full red.
    """
    if max_dist <= 0:
        return (0.2, 0.8, 0.2, 1.0)
    t = min(dist / max_dist, 1.0)
    if t < 0.5:
        r, g = t * 2, 1.0
    else:
        r, g = 1.0, 1.0 - (t - 0.5) * 2
    return (r, g, 0.15, 1.0)
