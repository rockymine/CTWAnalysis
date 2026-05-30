"""
Utility functions for decoding Minecraft NBT data from Anvil format.

Provides low-level functions for reading block data from chunk sections.
"""


def nibble(arr: bytes, i: int) -> int:
    """
    Extract a nibble (4 bits) from a byte array.

    In Minecraft's Anvil format, some arrays store two 4-bit values per byte.

    Args:
        arr: Byte array
        i: Index of the nibble to extract

    Returns:
        The 4-bit value (0-15) at the given index
    """
    byte_val = arr[i // 2]
    if i % 2 == 0:
        return byte_val & 0x0F
    else:
        return (byte_val >> 4) & 0x0F


def decode_block_id(blocks_array: bytes, add_array: bytes | None, index: int) -> int:
    """
    Decode the full block ID from Blocks and Add arrays.

    In Minecraft 1.8.9:
    - Blocks array contains the low 8 bits of block IDs
    - Add array (if present) contains the high 4 bits for block IDs > 255

    Args:
        blocks_array: The Blocks byte array from chunk section
        add_array: The Add nibble array (or None if not present)
        index: The block index (0-4095)

    Returns:
        The full block ID (0-4095)
    """
    low_bits = blocks_array[index] & 0xFF

    if add_array is not None:
        high_bits = nibble(add_array, index)
        return low_bits | (high_bits << 8)
    else:
        return low_bits


def decode_block_data(data_array: bytes, index: int) -> int:
    """
    Decode block metadata from the Data array.

    Args:
        data_array: The Data nibble array from chunk section
        index: The block index (0-4095)

    Returns:
        The block metadata value (0-15)
    """
    return nibble(data_array, index)


def get_block_index(x: int, y: int, z: int) -> int:
    """
    Calculate the array index for a block at local coordinates.

    Minecraft section arrays use the formula: (y * 16 + z) * 16 + x

    Args:
        x: Local X coordinate within section (0-15)
        y: Local Y coordinate within section (0-15)
        z: Local Z coordinate within section (0-15)

    Returns:
        Array index (0-4095)
    """
    return (y * 16 + z) * 16 + x
