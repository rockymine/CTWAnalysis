"""
Unit tests for NBT decoding utilities.

Tests nibble extraction, block ID decoding, and index mapping.
"""

import unittest
from layout_analysis.utils import nibble, decode_block_id, decode_block_data, get_block_index


class TestNibble(unittest.TestCase):
    """Test nibble extraction from byte arrays."""

    def test_nibble_even_index(self):
        """Test extracting lower nibble (even index)."""
        arr = bytes([0xAB, 0xCD, 0xEF])
        self.assertEqual(nibble(arr, 0), 0x0B)
        self.assertEqual(nibble(arr, 2), 0x0D)
        self.assertEqual(nibble(arr, 4), 0x0F)

    def test_nibble_odd_index(self):
        """Test extracting upper nibble (odd index)."""
        arr = bytes([0xAB, 0xCD, 0xEF])
        self.assertEqual(nibble(arr, 1), 0x0A)
        self.assertEqual(nibble(arr, 3), 0x0C)
        self.assertEqual(nibble(arr, 5), 0x0E)

    def test_nibble_all_zeros(self):
        """Test nibble extraction from zero bytes."""
        arr = bytes([0x00, 0x00])
        self.assertEqual(nibble(arr, 0), 0x00)
        self.assertEqual(nibble(arr, 1), 0x00)
        self.assertEqual(nibble(arr, 2), 0x00)
        self.assertEqual(nibble(arr, 3), 0x00)

    def test_nibble_all_ones(self):
        """Test nibble extraction from 0xFF bytes."""
        arr = bytes([0xFF, 0xFF])
        self.assertEqual(nibble(arr, 0), 0x0F)
        self.assertEqual(nibble(arr, 1), 0x0F)
        self.assertEqual(nibble(arr, 2), 0x0F)
        self.assertEqual(nibble(arr, 3), 0x0F)


class TestDecodeBlockId(unittest.TestCase):
    """Test block ID decoding with and without Add array."""

    def test_decode_without_add(self):
        """Test decoding block ID without Add array (IDs < 256)."""
        blocks = bytes([0, 1, 2, 255])
        self.assertEqual(decode_block_id(blocks, None, 0), 0)
        self.assertEqual(decode_block_id(blocks, None, 1), 1)
        self.assertEqual(decode_block_id(blocks, None, 2), 2)
        self.assertEqual(decode_block_id(blocks, None, 3), 255)

    def test_decode_with_add(self):
        """Test decoding block ID with Add array (IDs > 255)."""
        blocks = bytes([0x12, 0x34])
        # Add array: first byte = 0xAB means nibbles 0xB (index 0), 0xA (index 1)
        add = bytes([0xAB])

        # Index 0: low=0x12, high=0xB -> 0xB12
        self.assertEqual(decode_block_id(blocks, add, 0), 0x012 | (0xB << 8))
        self.assertEqual(decode_block_id(blocks, add, 0), 0xB12)

        # Index 1: low=0x34, high=0xA -> 0xA34
        self.assertEqual(decode_block_id(blocks, add, 1), 0x034 | (0xA << 8))
        self.assertEqual(decode_block_id(blocks, add, 1), 0xA34)

    def test_decode_air_block(self):
        """Test decoding air blocks (ID 0)."""
        blocks = bytes([0, 0, 0])
        self.assertEqual(decode_block_id(blocks, None, 0), 0)
        self.assertEqual(decode_block_id(blocks, None, 1), 0)

    def test_decode_common_blocks(self):
        """Test decoding common block IDs."""
        # Stone=1, Dirt=3, Bedrock=7, Sand=12, Glass=20
        blocks = bytes([1, 3, 7, 12, 20])
        self.assertEqual(decode_block_id(blocks, None, 0), 1)
        self.assertEqual(decode_block_id(blocks, None, 1), 3)
        self.assertEqual(decode_block_id(blocks, None, 2), 7)
        self.assertEqual(decode_block_id(blocks, None, 3), 12)
        self.assertEqual(decode_block_id(blocks, None, 4), 20)


class TestDecodeBlockData(unittest.TestCase):
    """Test block metadata decoding."""

    def test_decode_data_various_values(self):
        """Test decoding various metadata values."""
        # Byte 0xA3 = nibbles 0x3 (index 0), 0xA (index 1)
        data = bytes([0xA3, 0x5F])
        self.assertEqual(decode_block_data(data, 0), 0x3)
        self.assertEqual(decode_block_data(data, 1), 0xA)
        self.assertEqual(decode_block_data(data, 2), 0xF)
        self.assertEqual(decode_block_data(data, 3), 0x5)

    def test_decode_data_zeros(self):
        """Test decoding zero metadata."""
        data = bytes([0x00, 0x00])
        self.assertEqual(decode_block_data(data, 0), 0)
        self.assertEqual(decode_block_data(data, 1), 0)


class TestGetBlockIndex(unittest.TestCase):
    """Test block index calculation."""

    def test_index_corners(self):
        """Test index calculation for corner positions."""
        # (0, 0, 0) should be index 0
        self.assertEqual(get_block_index(0, 0, 0), 0)

        # (15, 0, 0) should be index 15
        self.assertEqual(get_block_index(15, 0, 0), 15)

        # (0, 0, 15) should be index 15*16 = 240
        self.assertEqual(get_block_index(0, 0, 15), 240)

        # (15, 0, 15) should be index 15*16 + 15 = 255
        self.assertEqual(get_block_index(15, 0, 15), 255)

        # (0, 15, 0) should be index 15*16*16 = 3840
        self.assertEqual(get_block_index(0, 15, 0), 3840)

        # (15, 15, 15) should be index 4095 (last block)
        self.assertEqual(get_block_index(15, 15, 15), 4095)

    def test_index_formula(self):
        """Test the index formula: (y * 16 + z) * 16 + x"""
        # Test a few arbitrary positions
        self.assertEqual(get_block_index(5, 3, 7), (3 * 16 + 7) * 16 + 5)
        self.assertEqual(get_block_index(5, 3, 7), 885)  # (48 + 7) * 16 + 5 = 885

        self.assertEqual(get_block_index(1, 2, 3), (2 * 16 + 3) * 16 + 1)
        self.assertEqual(get_block_index(1, 2, 3), 561)  # (32 + 3) * 16 + 1 = 561

    def test_index_range(self):
        """Test that all valid coordinates produce indices in range [0, 4095]."""
        for y in range(16):
            for z in range(16):
                for x in range(16):
                    index = get_block_index(x, y, z)
                    self.assertGreaterEqual(index, 0)
                    self.assertLessEqual(index, 4095)


if __name__ == '__main__':
    unittest.main()
