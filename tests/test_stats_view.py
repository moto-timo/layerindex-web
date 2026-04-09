# layerindex-web - tests for StatsView
#
# Copyright (C) 2026 Konsulko Group
#
# Licensed under the MIT license, see COPYING.MIT for details
#
# SPDX-License-Identifier: MIT

# Tests for bug #15391 - Statistics page timeout
# https://bugzilla.yoctoproject.org/show_bug.cgi?id=15391
#
# The fix replaces a single annotated queryset (which generated one huge SQL
# query with multiple COUNT(DISTINCT ...) JOINs) with per-branch individual
# COUNT queries that are much cheaper at production data volumes.

import pytest
from django.test import TestCase
from django.urls import reverse

from layerindex.models import (Branch, LayerItem, LayerBranch, Recipe,
                                BBClass, Machine, Distro)


@pytest.mark.django_db
class TestStatsView(TestCase):
    """Tests for StatsView (bug #15391 - statistics page timeout fix)."""

    def setUp(self):
        # Create two visible branches with different sort priorities
        self.branch1 = Branch.objects.create(
            name='main',
            bitbake_branch='master',
            short_description='Main branch',
            sort_priority=1,
            hidden=False,
            updates_enabled=True,
        )
        self.branch2 = Branch.objects.create(
            name='wrynose',
            bitbake_branch='2.18',
            short_description='Wrynose branch',
            sort_priority=2,
            hidden=False,
            updates_enabled=False,
        )
        # A hidden branch that should never appear in perbranch
        self.branch_hidden = Branch.objects.create(
            name='old-hidden',
            bitbake_branch='1.0',
            short_description='Old hidden branch',
            sort_priority=99,
            hidden=True,
            updates_enabled=False,
        )

        # A layer
        self.layer = LayerItem.objects.create(
            name='meta-test',
            status='P',
            layer_type='A',
            summary='Test layer',
            description='A test layer',
            vcs_url='git://example.com/meta-test.git',
        )

        # Wire up layerbranches
        self.lb1 = LayerBranch.objects.create(layer=self.layer, branch=self.branch1)
        self.lb2 = LayerBranch.objects.create(layer=self.layer, branch=self.branch2)

        # Add objects only to branch1
        Recipe.objects.create(
            layerbranch=self.lb1,
            filename='test_1.0.bb',
            pn='test',
            pv='1.0',
            filepath='recipes-test',
        )
        BBClass.objects.create(
            layerbranch=self.lb1,
            name='testclass',
        )
        Machine.objects.create(
            layerbranch=self.lb1,
            name='qemux86',
            description='QEMU x86 machine',
        )
        Distro.objects.create(
            layerbranch=self.lb1,
            name='testdistro',
            description='Test distro',
        )

    def test_stats_view_returns_200(self):
        """StatsView should return HTTP 200."""
        response = self.client.get(reverse('stats'))
        self.assertEqual(response.status_code, 200)

    def test_perbranch_is_list_of_dicts(self):
        """perbranch context should be a list of dicts, not a queryset."""
        response = self.client.get(reverse('stats'))
        perbranch = response.context['perbranch']
        self.assertIsInstance(perbranch, list)
        for item in perbranch:
            self.assertIsInstance(item, dict)

    def test_perbranch_excludes_hidden_branches(self):
        """Hidden branches should not appear in perbranch."""
        response = self.client.get(reverse('stats'))
        names = [b['name'] for b in response.context['perbranch']]
        self.assertIn('main', names)
        self.assertIn('wrynose', names)
        self.assertNotIn('old-hidden', names)

    def test_perbranch_sorted_by_priority(self):
        """Branches should be ordered by sort_priority."""
        response = self.client.get(reverse('stats'))
        names = [b['name'] for b in response.context['perbranch']]
        self.assertEqual(names, ['master', 'main', 'wrynose'])

    def test_perbranch_dict_has_required_keys(self):
        """Each perbranch dict must contain all keys the template expects."""
        required_keys = {'name', 'updates_enabled', 'layer_count',
                         'recipe_count', 'class_count', 'machine_count', 'distro_count'}
        response = self.client.get(reverse('stats'))
        for item in response.context['perbranch']:
            self.assertTrue(required_keys.issubset(item.keys()),
                            f"Missing keys in perbranch item: {required_keys - item.keys()}")

    def test_perbranch_counts_branch1(self):
        """Per-branch counts for branch1 should reflect the test data."""
        response = self.client.get(reverse('stats'))
        branch1_data = next(b for b in response.context['perbranch'] if b['name'] == 'main')
        self.assertEqual(branch1_data['layer_count'], 1)
        self.assertEqual(branch1_data['recipe_count'], 1)
        self.assertEqual(branch1_data['class_count'], 1)
        self.assertEqual(branch1_data['machine_count'], 1)
        self.assertEqual(branch1_data['distro_count'], 1)
    
    def test_perbranch_counts_branch2_empty(self):
        """Branch2 has a layerbranch but no recipes/classes/machines/distros."""
        response = self.client.get(reverse('stats'))
        branch2_data = next(b for b in response.context['perbranch'] if b['name'] == 'wrynose')
        self.assertEqual(branch2_data['layer_count'], 1)
        self.assertEqual(branch2_data['recipe_count'], 0)
        self.assertEqual(branch2_data['class_count'], 0)
        self.assertEqual(branch2_data['machine_count'], 0)
        self.assertEqual(branch2_data['distro_count'], 0)

    def test_perbranch_updates_enabled_field(self):
        """updates_enabled should be correctly reflected per branch."""
        response = self.client.get(reverse('stats'))
        perbranch = response.context['perbranch']
        b1 = next(b for b in perbranch if b['name'] == 'main')
        b2 = next(b for b in perbranch if b['name'] == 'wrynose')
        self.assertTrue(b1['updates_enabled'])
        self.assertFalse(b2['updates_enabled'])

    def test_overall_context_keys_present(self):
        """Overall statistics context keys should all be present."""
        response = self.client.get(reverse('stats'))
        for key in ('layercount', 'recipe_count_distinct', 'class_count_distinct',
                    'machine_count_distinct', 'distro_count_distinct'):
            self.assertIn(key, response.context,
                          f"Missing context key: {key}")
