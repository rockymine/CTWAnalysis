"""Data classes for parsed map XML data."""

from dataclasses import dataclass, field
from typing import Optional

from .regions import Region


@dataclass
class Team:
    """Team information."""
    id: str
    color: str
    max_players: int = 0
    min_players: int = 0
    name: str = ""
    dye_color: str = ""


@dataclass
class Author:
    """Author or contributor entry from <authors> block."""
    uuid: str = ""
    role: str = "author"          # "author" | "contributor"
    contribution: str = ""        # optional contribution note, e.g. "xml"


@dataclass
class KitItem:
    """A single inventory item slot within a kit."""
    slot: int = 0
    material: str = ""
    amount: int = 1
    item_damage: int = 0
    unbreakable: bool = False
    team_color: bool = False
    enchantments: str = ""        # comma-joined "name:level" pairs, e.g. "sharpness:2,fire_aspect:1"


@dataclass
class KitArmor:
    """A single armor slot within a kit."""
    slot_name: str = ""           # helmet | chestplate | leggings | boots
    material: str = ""
    unbreakable: bool = False
    team_color: bool = False
    enchantments: str = ""


@dataclass
class Kit:
    """A kit definition parsed from a <kit> element."""
    id: str = ""
    items: list[KitItem] = field(default_factory=list)
    armor: list[KitArmor] = field(default_factory=list)


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
    location: tuple[float, float, float]
    monument: tuple[float, float, float]
    monument_region_id: Optional[str] = None  # set when monument="region-id" attribute form is used
    wool_room_region: Optional[str] = None    # detected from spawners / chests / spatial search


@dataclass
class SpawnerItem:
    """A single item dropped by a <spawner> element."""
    material: str
    damage: int = 0
    amount: int = 1


@dataclass
class WoolSpawner:
    """A <spawner> element that periodically drops items into a region.

    In CTW maps these are used exclusively to respawn wool blocks after
    they are picked up.  ``player_region`` is the wool room (players
    must be present to activate the spawner); ``spawn_region`` is where
    the wool item appears.
    """
    spawn_region: str
    player_region: str
    delay: str = ""
    max_entities: Optional[int] = None
    items: list[SpawnerItem] = field(default_factory=list)


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
class Renewable:
    """A <renewable> element that regenerates broken blocks inside a region.

    In CTW maps, renewables are typically used for iron/gold block regeneration
    at spawn areas.  The ``renew_filter`` and ``replace_filter`` fields are stored
    as raw filter-ID strings (or empty when an inline filter child is used).
    """
    region_id: str = ""            # region attribute on the <renewable> element
    rate: float = 1.0              # blocks regenerated per second
    renew_filter: str = ""         # filter-id reference for which blocks regenerate
    replace_filter: str = ""       # filter-id reference for what can be replaced
    grow: bool = False             # whether regeneration spreads from existing blocks


@dataclass
class BlockDropItem:
    """A single <item> inside a <block-drops> rule's <drops> child."""
    material: str = ""
    damage: int = 0
    amount: int = 1
    chance: float = 1.0


@dataclass
class BlockDropRule:
    """A <rule> element inside a <block-drops> block.

    Specifies custom drop behaviour (and optional block replacement) when a
    block matching ``filter_id`` is broken inside ``region_id``.
    """
    region_id: str = ""            # region attribute (empty = global)
    filter_id: str = ""            # filter attribute (which blocks trigger the rule)
    replacement: str = ""          # material placed where the broken block was
    wrong_tool: bool = False       # apply even when the wrong tool is used
    items: list[BlockDropItem] = field(default_factory=list)


@dataclass
class MapData:
    """Complete map data."""
    name: str = ""
    version: str = ""
    gamemode: str = ""
    objective: str = ""
    authors: list[Author] = field(default_factory=list)
    kits: list[Kit] = field(default_factory=list)
    teams: list[Team] = field(default_factory=list)
    spawns: list[Spawn] = field(default_factory=list)
    observer_spawn: Optional[Spawn] = None
    wools: list[Wool] = field(default_factory=list)
    spawners: list[WoolSpawner] = field(default_factory=list)
    renewables: list[Renewable] = field(default_factory=list)
    block_drop_rules: list[BlockDropRule] = field(default_factory=list)
    regions: dict[str, Region] = field(default_factory=dict)
    apply_rules: list[ApplyRule] = field(default_factory=list)
    max_build_height: Optional[int] = None


@dataclass
class MapXmlContext:
    """Pipeline result of the XML analysis step.

    Passed between pipeline stages so downstream steps (assembly, POI
    annotation) do not need to re-parse map.xml or read map_data.json.
    The JSON file written by the xml step is an artifact for human
    inspection only.
    """
    map_data: MapData
    region_categories: dict[str, list[str]] = field(default_factory=dict)
