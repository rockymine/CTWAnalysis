"""Data classes for parsed map XML data."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .regions import Region


@dataclass
class Team:
    """Team information."""
    id: str
    color: str
    max_players: int = 0
    name: str = ""
    dye_color: str = ""


@dataclass
class Spawn:
    """Spawn point information."""
    team: str = ""
    kit: str = ""
    yaw: float = 0.0
    region: Optional[Region] = None


@dataclass
class Wool:
    """Wool objective information."""
    team: str
    color: str
    location: Tuple[float, float, float]
    monument: Tuple[float, float, float]


@dataclass
class ApplyRule:
    """An <apply> element that binds filters to regions."""
    block_filter: str = ""
    block_place_filter: str = ""
    block_break_filter: str = ""
    use_filter: str = ""
    region_id: str = ""
    inline_region: Optional[Region] = None
    message: str = ""


@dataclass
class MapData:
    """Complete map data."""
    name: str = ""
    version: str = ""
    objective: str = ""
    teams: List[Team] = field(default_factory=list)
    spawns: List[Spawn] = field(default_factory=list)
    wools: List[Wool] = field(default_factory=list)
    regions: Dict[str, Region] = field(default_factory=dict)
    apply_rules: List[ApplyRule] = field(default_factory=list)
    max_build_height: Optional[int] = None
