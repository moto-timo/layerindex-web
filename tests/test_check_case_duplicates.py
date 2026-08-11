# layerindex-web - tests for layerindex/tools/check_case_duplicates.py
#
# Licensed under the MIT license, see COPYING.MIT for details
#
# SPDX-License-Identifier: MIT
#
# AI-generated, Claude Opus 5.5

import importlib.util
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.db import connection

spec = importlib.util.spec_from_file_location(
    'check_case_duplicates',
    Path(__file__).parent.parent / 'layerindex' / 'tools' / 'check_case_duplicates.py')
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

pytestmark = pytest.mark.django_db


def test_unique_text_fields_are_found():
    assert (User, 'username') in tool.find_unique_text_fields()


def test_no_duplicates(capsys):
    User.objects.create_user('tim')
    User.objects.create_user('paul')
    assert tool.main() == 0
    assert 'No case-variant duplicates' in capsys.readouterr().out


@pytest.mark.skipif(connection.vendor == 'mysql',
                    reason="MariaDB's collation already rejects names that differ only in case")
def test_duplicates_differing_in_case(capsys):
    tim = User.objects.create_user('tim')
    tim2 = User.objects.create_user('Tim')
    # Which of the two comes first depends on the collation
    [pair] = tool.find_case_duplicates(User, 'username')
    assert set(pair) == {(tim.pk, 'tim'), (tim2.pk, 'Tim')}
    assert tool.main() == 1
    out = capsys.readouterr().out
    assert 'User.username:' in out and "'Tim'" in out and "'tim'" in out
