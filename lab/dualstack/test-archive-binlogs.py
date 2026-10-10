#!/usr/bin/env python3
"""Falhas controladas em arquivos temporários; integração real é registrada à parte."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('archive', Path(__file__).with_name('archive-binlogs.py'))
archive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive)


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.src = self.root / 'binlog.000001'
        self.src.write_bytes(os.urandom(16384))
        self.dst = self.root / 'copy'

    def copy(self):
        return archive.copy_verified(self.src, self.dst, self.src.stat().st_size, 256)

    def test_copy_and_reentry(self):
        first = self.copy()
        again = self.copy()
        self.assertEqual(first['sha256'], again['sha256'])
        self.assertEqual(again['copied_bytes'], 0)

    def test_restart_partial_copy(self):
        self.dst.with_name('copy.partial').write_bytes(b'incomplete')
        self.copy()
        self.assertEqual(self.src.read_bytes(), self.dst.read_bytes())

    def test_existing_corruption_stops(self):
        self.copy()
        self.dst.write_bytes(b'X' * self.src.stat().st_size)
        with self.assertRaisesRegex(RuntimeError, 'hash_mismatch'):
            self.copy()

    def test_wrong_size_stops(self):
        with self.assertRaisesRegex(RuntimeError, 'source_size_changed'):
            archive.copy_verified(self.src, self.dst, 1)

    def test_write_failure_leaves_source(self):
        with patch.object(archive.os, 'fsync', side_effect=OSError('injected_enospc')):
            with self.assertRaisesRegex(OSError, 'injected_enospc'):
                self.copy()
        self.assertTrue(self.src.exists())
        self.assertFalse(self.dst.exists())
        self.copy()

    def test_no_mount_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'archive_not_mounted'):
            archive.verify_mount(self.root)

    def test_partial_symlink_rejected(self):
        self.dst.with_name('copy.partial').symlink_to(self.src)
        with self.assertRaisesRegex(RuntimeError, 'partial_symlink'):
            self.copy()

    def test_manifest_atomic(self):
        target = self.root / 'manifest.json'
        archive.write_json(target, {'sha256': 'test'})
        self.assertEqual(json.loads(target.read_text()), {'sha256': 'test'})

    def test_inventory_recovers_after_rotation(self):
        responses = [[['binlog.000001', '100', 'No']], [['binlog.000002']],
                     [['binlog.000001', '120', 'No'], ['binlog.000002', '180', 'No']], [['binlog.000002']]]
        with patch.object(archive, 'mysql', side_effect=responses) as sql, patch.object(archive.time, 'sleep') as sleep:
            self.assertEqual(archive.inventory(), [('binlog.000001', 120), ('binlog.000002', 180)])
            self.assertEqual(sql.call_count, 4)
            sleep.assert_called_once_with(.1)
            self.assertTrue(all(0 < call.kwargs['timeout'] <= 5 for call in sql.call_args_list))

    def test_inventory_stops_after_three_rotations(self):
        responses = [[['binlog.000001', '100', 'No']], [['binlog.000002']]] * 3
        with patch.object(archive, 'mysql', side_effect=responses) as sql, patch.object(archive.time, 'sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, 'rotation_during_inventory_retry_later'):
                archive.inventory()
            self.assertEqual(sql.call_count, 6)
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [.1, .2])

    def test_inventory_budget_includes_queries(self):
        elapsed = [0.]
        timeouts = []
        def slow_query(sql, *, timeout):
            timeouts.append(timeout)
            elapsed[0] += 3
            return [['binlog.000001', '100', 'No']]
        with patch.object(archive.time, 'monotonic', side_effect=lambda: elapsed[0]), patch.object(archive, 'mysql', side_effect=slow_query):
            with self.assertRaisesRegex(RuntimeError, 'binlog_inventory_timeout'):
                archive.inventory()
        self.assertEqual(timeouts, [5., 2.])

    def test_inventory_budget_includes_backoff(self):
        elapsed = [0.]
        def query(sql, *, timeout):
            elapsed[0] += 2.46
            return [['binlog.000001', '100', 'No']] if 'BINARY' in sql else [['binlog.000002']]
        with patch.object(archive.time, 'monotonic', side_effect=lambda: elapsed[0]), patch.object(archive, 'mysql', side_effect=query) as sql, patch.object(archive.time, 'sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, 'binlog_inventory_timeout'):
                archive.inventory()
            self.assertEqual(sql.call_count, 2)
            sleep.assert_not_called()

    def test_inventory_does_not_retry_sql_error_or_timeout(self):
        for error, message in [(RuntimeError('mysql_command_failed'), 'mysql_command_failed'),
                               (subprocess.TimeoutExpired('mysql', 5), 'binlog_inventory_timeout')]:
            with self.subTest(error=message), patch.object(archive, 'mysql', side_effect=error) as sql:
                with self.assertRaisesRegex(RuntimeError, message):
                    archive.inventory()
                sql.assert_called_once()

    def test_inventory_rejects_empty_encrypted_or_invalid_logs(self):
        for logs in ([], [['binlog.000001', '100', 'Yes']], [['foreign.000001', '100', 'No']]):
            with self.subTest(logs=logs), patch.object(archive, 'mysql', return_value=logs) as sql:
                with self.assertRaisesRegex(RuntimeError, 'unexpected_binlog_format_or_encryption'):
                    archive.inventory()
                sql.assert_called_once()

    def test_inventory_rejects_missing_master(self):
        with patch.object(archive, 'mysql', side_effect=[[['binlog.000001', '100', 'No']], []]) as sql:
            with self.assertRaisesRegex(RuntimeError, 'missing_active_binlog'):
                archive.inventory()
            self.assertEqual(sql.call_count, 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
