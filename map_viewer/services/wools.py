from typing import Optional


_WOOL_COLOR_DAMAGE: dict[str, int] = {
    'white': 0, 'orange': 1, 'magenta': 2, 'light_blue': 3,
    'yellow': 4, 'lime': 5, 'pink': 6, 'gray': 7,
    'light_gray': 8, 'cyan': 9, 'purple': 10, 'blue': 11,
    'brown': 12, 'green': 13, 'red': 14, 'black': 15,
}


def wool_color_to_damage(color: str) -> Optional[int]:
    """Return the Minecraft damage value for a wool color name, or None."""
    # Handle names with spaces or underscores (e.g. 'light blue' → 'light_blue')
    normalized = color.lower().replace(' ', '_')
    return _WOOL_COLOR_DAMAGE.get(normalized)
