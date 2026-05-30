"""Minecraft block ID → RGB colour lookup.

Based on Minecraft's MapColor enum (1.8/1.9 source).  Stained blocks
(wool=35, stained glass=95, stained clay=159, carpet=171) use their
damage value as a sub-colour index into _STAIN_COLORS.
"""

import numpy as np

_STAIN_COLORS: dict[int, tuple[int, int, int]] = {
    0:  (221, 221, 221),  1:  (216, 127,  51),  2:  (178,  76, 216),
    3:  (102, 153, 216),  4:  (229, 229,  51),  5:  (127, 204,  25),
    6:  (242, 127, 165),  7:  ( 76,  76,  76),  8:  (153, 153, 153),
    9:  ( 76, 127, 153),  10: (127,  63, 178),  11: ( 51,  76, 178),
    12: (102,  76,  51),  13: (102, 127,  51),  14: (153,  51,  51),
    15: ( 25,  25,  25),
}

_BLOCK_COLORS: dict[tuple[int, int], tuple[int, int, int]] = {}


def _bc(bid: int, r: int, g: int, b: int, data: int = -1) -> None:
    _BLOCK_COLORS[(bid, data)] = (r, g, b)


def _bc_stained(bid: int) -> None:
    for meta, rgb in _STAIN_COLORS.items():
        _BLOCK_COLORS[(bid, meta)] = rgb
    _BLOCK_COLORS[(bid, -1)] = _STAIN_COLORS[0]


_bc(0,    0,   0,   0)    # air
_bc(1,  112, 112, 112)    # stone
_bc(2,  127, 178,  56)    # grass
_bc(3,  151,  94,  61)    # dirt
_bc(4,  112, 112, 112)    # cobblestone
_bc(7,   80,  80,  80)    # bedrock
_bc(8,   64,  64, 255)    # water flowing
_bc(9,   64,  64, 255)    # water stationary
_bc(10, 255,  90,   0)    # lava flowing
_bc(11, 255,  90,   0)    # lava stationary
_bc(12, 247, 214, 163)    # sand
_bc(13, 150, 140, 130)    # gravel
_bc(14, 143, 119,  72)    # gold ore
_bc(15, 112, 112, 112)    # iron ore
_bc(16, 112, 112, 112)    # coal ore
_bc(17, 143, 119,  72)    # wood log
_bc(18,   0, 124,   0)    # leaves
_bc(19, 200, 200,  80)    # sponge
_bc(20, 180, 210, 230)    # glass
_bc(21,  51,  76, 178)    # lapis ore
_bc(22,  74, 144, 226)    # lapis block
_bc(24, 230, 200, 140)    # sandstone
_bc(25, 143, 119,  72)    # note block
_bc(26, 180, 100, 100)    # bed
_bc(30, 220, 220, 220)    # cobweb
_bc(31,   0, 160,   0)    # tall grass
_bc(35,  -1,  -1,  -1)    # wool — stained below
_bc(36, 255,   0, 255)    # piston extension — vibrant magenta for visibility
_bc(41, 250, 238,  77)    # gold block
_bc(42, 200, 200, 210)    # iron block
_bc(43, 120, 120, 120)    # stone double slab
_bc(44, 120, 120, 120)    # stone slab
_bc(45, 168,  70,  55)    # brick
_bc(46, 255,  40,  40)    # TNT
_bc(47, 143, 119,  72)    # bookshelf
_bc(48, 100, 130, 100)    # mossy cobblestone
_bc(49,  35,  20,  55)    # obsidian
_bc(53, 143, 119,  72)    # oak stairs
_bc(54, 143, 100,  50)    # chest
_bc(55, 200,   0,   0)    # redstone wire
_bc(57,  94, 237, 255)    # diamond block
_bc(58, 143, 100,  50)    # crafting table
_bc(61,  80,  80,  80)    # furnace
_bc(67, 112, 112, 112)    # cobblestone stairs
_bc(77, 112, 112, 112)    # stone button
_bc(80, 240, 240, 255)    # snow block
_bc(85, 143, 119,  72)    # oak fence
_bc(87, 112,   2,   0)    # netherrack
_bc(88, 100,  80,  50)    # soul sand
_bc(89, 240, 200, 100)    # glowstone
_bc(91, 240, 150,  20)    # jack o lantern
_bc(95,  -1,  -1,  -1)    # stained glass — stained below
_bc(96, 143, 119,  72)    # trapdoor
_bc(97, 112, 112, 112)    # monster egg
_bc(98, 112, 112, 112)    # stone bricks
_bc(103, 100, 170,  40)   # melon
_bc(106,   0, 160,   0)   # vine
_bc(107, 143, 119,  72)   # fence gate
_bc(108, 168,  70,  55)   # brick stairs
_bc(109, 112, 112, 112)   # stone brick stairs
_bc(111,  60, 130,  40)   # lily pad
_bc(112,  45,  20,  20)   # nether brick
_bc(120,  80,  80,  40)   # end portal frame
_bc(121, 220, 220, 180)   # end stone
_bc(123, 100,  80,  40)   # redstone lamp off
_bc(124, 240, 200, 100)   # redstone lamp on
_bc(125, 143, 119,  72)   # wood double slab
_bc(126, 143, 119,  72)   # wood slab
_bc(128, 230, 200, 140)   # sandstone stairs
_bc(129, 100, 200, 100)   # emerald ore
_bc(130, 143, 100,  50)   # ender chest
_bc(131, 143, 119,  72)   # tripwire hook
_bc(133,   0, 200,  60)   # emerald block
_bc(134, 110,  80,  50)   # spruce stairs
_bc(135, 143, 119,  72)   # birch stairs
_bc(136, 120,  80,  40)   # jungle stairs
_bc(138,  80, 220, 240)   # beacon
_bc(139, 112, 112, 112)   # cobblestone wall
_bc(143, 143, 119,  72)   # wood button
_bc(144, 100, 100, 100)   # mob head
_bc(145, 200, 200, 210)   # anvil
_bc(146, 143, 100,  50)   # trapped chest
_bc(148, 200, 200, 210)   # heavy pressure plate
_bc(155, 240, 235, 220)   # quartz block
_bc(156, 240, 235, 220)   # quartz stairs
_bc(159,  -1,  -1,  -1)   # stained hardened clay — stained below
_bc(160,  -1,  -1,  -1)   # stained glass pane — stained below
_bc(161,   0, 124,   0)   # acacia leaves
_bc(162, 143, 119,  72)   # acacia/dark oak log
_bc(163, 110,  80,  50)   # acacia stairs
_bc(164, 110,  60,  30)   # dark oak stairs
_bc(165, 200, 220,  80)   # slime block
_bc(166, 255,   0,   0)   # barrier
_bc(167, 200, 200, 210)   # iron trapdoor
_bc(168,  66, 140, 120)   # prismarine
_bc(169,  80, 220, 240)   # sea lantern
_bc(170, 215, 185,  35)   # hay bale
_bc(171,  -1,  -1,  -1)   # carpet — stained below
_bc(172, 160,  90,  40)   # hardened clay
_bc(173,  25,  25,  25)   # coal block
_bc(174, 200, 220, 255)   # packed ice
_bc(179, 230, 200, 140)   # red sandstone
_bc(180, 230, 200, 140)   # red sandstone stairs
_bc(181, 230, 200, 140)   # double red sandstone slab
_bc(182, 230, 200, 140)   # red sandstone slab
_bc(183, 110,  60,  30)   # spruce fence gate
_bc(184, 190, 160, 100)   # birch fence gate
_bc(185, 120,  80,  40)   # jungle fence gate
_bc(186, 110,  60,  30)   # dark oak fence gate
_bc(187, 143, 119,  72)   # acacia fence gate
_bc(188, 110,  80,  50)   # spruce fence
_bc(189, 190, 160, 100)   # birch fence
_bc(190, 120,  80,  40)   # jungle fence
_bc(191, 110,  60,  30)   # dark oak fence
_bc(192, 143, 119,  72)   # acacia fence
_bc(193, 190, 160, 100)   # spruce door
_bc(196, 110,  60,  30)   # dark oak door

for _bid in (35, 95, 159, 160, 171):
    _bc_stained(_bid)


def block_color(block_id: int, block_data: int) -> tuple[int, int, int]:
    """Return (r, g, b) for a Minecraft block ID + data value.

    Falls back to a deterministic hash colour for unknown blocks.
    """
    key = (block_id, block_data)
    if key in _BLOCK_COLORS:
        return _BLOCK_COLORS[key]
    key2 = (block_id, -1)
    if key2 in _BLOCK_COLORS:
        return _BLOCK_COLORS[key2]
    rng = np.random.default_rng(block_id * 1000 + block_data)
    return tuple(int(x) for x in rng.integers(80, 220, size=3))
