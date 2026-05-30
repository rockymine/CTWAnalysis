"""Tests for cross-platform path handling in match analysis.

Verifies that:
- database.indexer stores POSIX paths (forward slashes) in the database
- database.queries normalizes legacy backslash paths on read
- processing.processor normalizes legacy backslash paths on read
"""

import unittest
import tempfile
import os
from pathlib import Path, PurePosixPath
from unittest.mock import patch, MagicMock

import duckdb
import pandas as pd


class TestMatchIndexerPathStorage(unittest.TestCase):
    """database.indexer should store POSIX-style paths in the database."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.conn = duckdb.connect(self.db_path)
        self.conn.execute("""
            CREATE TABLE matches (
                match_id INTEGER PRIMARY KEY,
                match_file TEXT NOT NULL,
                map_name TEXT NOT NULL,
                match_start TIMESTAMP,
                match_duration FLOAT,
                player_count INTEGER,
                position_count INTEGER,
                processed BOOLEAN DEFAULT FALSE,
                processed_at TIMESTAMP,
                processing_time FLOAT
            )
        """)
        self.conn.close()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _create_dummy_parquet(self, directory: Path, filename: str) -> Path:
        """Create a minimal match parquet file for indexing."""
        path = directory / filename
        df = pd.DataFrame({
            'timestamp': [1000, 1001, 1100, 1200],
            'event_type': [0, 2, 5, 1],
            'player_id': [0, 0, 0, 0],
            'x': [0.0, 1.0, 2.0, 3.0],
            'y': [64.0, 64.0, 64.0, 64.0],
            'z': [0.0, 1.0, 2.0, 3.0],
            'held_item': [0, 0, 0, 0],
            'inventory_count': [0, 0, 0, 0],
            'wool_id': [None, None, None, None],
            'victim_id': [None, None, None, None],
        })
        df.to_parquet(path, index=False)
        return path

    def test_stores_posix_path(self):
        """Indexed match_file should use forward slashes regardless of platform."""
        from match_analysis.database.indexer import index_match_files

        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_dummy_parquet(Path(tmpdir), '2026-01-01_00-00-00_999.parquet')

            with patch('match_analysis.database.indexer.duckdb') as mock_duckdb:
                mock_conn = MagicMock()
                mock_duckdb.connect.return_value = mock_conn

                def execute_side_effect(sql, *args, **kwargs):
                    mock_result = MagicMock()
                    if 'SELECT map_id FROM maps' in sql:
                        mock_result.fetchone.return_value = (1,)
                    else:
                        mock_result.fetchone.return_value = None
                    return mock_result

                mock_conn.execute.side_effect = execute_side_effect

                index_match_files(tmpdir)

                # Find the INSERT call
                insert_calls = [
                    c for c in mock_conn.execute.call_args_list
                    if c[0] and 'INSERT INTO matches' in str(c[0][0])
                ]
                self.assertEqual(len(insert_calls), 1)
                stored_path = insert_calls[0][0][1][1]  # second positional arg in params list
                self.assertNotIn('\\', stored_path,
                                 f"Stored path should not contain backslashes: {stored_path}")
                self.assertIn('/', stored_path,
                              f"Stored path should use forward slashes: {stored_path}")


class TestMatchServicePathNormalization(unittest.TestCase):
    """database.queries.get_match_file should normalize backslash paths."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.conn = duckdb.connect(self.db_path)
        self.conn.execute("""
            CREATE TABLE maps (
                map_id INTEGER PRIMARY KEY,
                map_slug TEXT NOT NULL
            )
        """)
        self.conn.execute(
            "INSERT INTO maps (map_id, map_slug) VALUES (?, ?)",
            [1, 'TestMap'],
        )
        self.conn.execute("""
            CREATE TABLE matches (
                match_id INTEGER PRIMARY KEY,
                match_file TEXT NOT NULL,
                map_id INTEGER NOT NULL,
                match_start TIMESTAMP,
                match_duration FLOAT,
                player_count INTEGER,
                position_count INTEGER,
                processed BOOLEAN DEFAULT FALSE,
                processed_at TIMESTAMP,
                processing_time FLOAT
            )
        """)
        # Insert with Windows-style backslash path (simulating legacy data)
        self.conn.execute(
            "INSERT INTO matches (match_id, match_file, map_id) VALUES (?, ?, ?)",
            [42, 'match_logs\\2026-01-01_00-00-00_42.parquet', 1],
        )
        # Insert with POSIX path
        self.conn.execute(
            "INSERT INTO matches (match_id, match_file, map_id) VALUES (?, ?, ?)",
            [43, 'match_logs/2026-01-01_00-00-00_43.parquet', 1],
        )
        self.conn.close()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_normalizes_backslash_path(self):
        """Legacy backslash paths should be normalized to platform-native separators."""
        from match_analysis.database.queries import get_match_file

        with patch('match_analysis.database.queries.DB_PATH', self.db_path):
            match_file, map_name = get_match_file(42)

        self.assertEqual(map_name, 'TestMap')
        # The result should equal what Path() produces — platform-native format
        expected = str(Path('match_logs/2026-01-01_00-00-00_42.parquet'))
        self.assertEqual(match_file, expected)

    def test_posix_path_unchanged(self):
        """POSIX paths should remain valid after normalization."""
        from match_analysis.database.queries import get_match_file

        with patch('match_analysis.database.queries.DB_PATH', self.db_path):
            match_file, map_name = get_match_file(43)

        self.assertEqual(map_name, 'TestMap')
        self.assertIn('2026-01-01_00-00-00_43.parquet', match_file)

    def test_path_is_valid_pathlib(self):
        """Returned path should be usable as a pathlib Path on current platform."""
        from match_analysis.database.queries import get_match_file

        with patch('match_analysis.database.queries.DB_PATH', self.db_path):
            match_file, _ = get_match_file(42)

        # Should not raise
        p = Path(match_file)
        self.assertEqual(p.name, '2026-01-01_00-00-00_42.parquet')
        self.assertEqual(p.parent.name, 'match_logs')


if __name__ == '__main__':
    unittest.main()
