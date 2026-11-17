# layerindex-web - tests for layerindex/tools/copy_mariadb_to_postgresql.py
#
# Licensed under the MIT license, see COPYING.MIT for details
#
# SPDX-License-Identifier: MIT
#
# AI-generated, Claude Opus 5.5

# The copy itself needs both databases at once, so it was tested by hand
# against MariaDB and PostgreSQL containers. These tests cover how values are
# changed on the way and compared afterwards.

import datetime
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    'copy_mariadb_to_postgresql',
    Path(__file__).parent.parent / 'layerindex' / 'tools' / 'copy_mariadb_to_postgresql.py')
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def test_convert_row_makes_booleans_and_drops_nul():
    row, nul = tool.convert_row((1, 0, None, 'a\x00b', 'plain', None), booleans=[0, 1, 2],
                                texts=[3, 4, 5])
    assert row == [True, False, None, 'ab', 'plain', None]
    assert nul == 1


def test_convert_row_leaves_other_columns_alone():
    when = datetime.datetime(2026, 11, 1, 12)
    row, nul = tool.convert_row((7, when, 'x\x00'), booleans=[], texts=[])
    assert row == [7, when, 'x\x00']
    assert nul == 0


def test_normalise_matches_values_from_both_databases():
    utc_noon = datetime.datetime(2026, 11, 1, 12)
    pacific = datetime.timezone(datetime.timedelta(hours=-8))
    # MariaDB reads 0/1 and a naive datetime; PostgreSQL True/False and an aware one
    assert tool.normalise(True) == tool.normalise(1)
    assert tool.normalise(False) == tool.normalise(0)
    assert tool.normalise(datetime.datetime(2026, 11, 1, 4, tzinfo=pacific)) == utc_noon
    assert tool.normalise(utc_noon) == utc_noon
    # A value copied without its NUL still compares equal
    assert tool.normalise('a\x00b') == tool.normalise('ab')
