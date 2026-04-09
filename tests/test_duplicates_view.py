# layerindex-web - tests for DuplicatesView
#
# Copyright (C) 2026 Tim Orling <tim.orling@konsulko.com>
#
# Licensed under the MIT license, see COPYING.MIT for details
#
# SPDX-License-Identifier: MIT

# Tests for bug #16175 - Duplicates page timeout
# https://bugzilla.yoctoproject.org/show_bug.cgi?id=16175
#
# The original code had two performance problems:
#
# 1. Python list comprehension IN clause: each get_* method pulled all
#    duplicate names into Python memory and built a huge IN (...) literal.
#    Fixed by passing the 'dupes' queryset directly so Django emits a subquery.
#
# 2. Per-row correlated subquery: get_recipes() called recipes_preferred_count()
#    which embeds a correlated subquery via .extra() evaluated once per result
#    row by the database.  With hundreds of duplicate recipes this caused a 504
#    Gateway Timeout.  Fixed by computing preferred_count with a single batch
#    MAX query over all pns, then annotating results in Python.

import pytest
from django.test import TestCase
from django.urls import reverse

from layerindex.models import (Branch, LayerItem, LayerBranch, Recipe,
                                BBClass, IncFile)


@pytest.mark.django_db
class TestDuplicatesView(TestCase):
    """Tests for DuplicatesView (bug #16175 - duplicates page timeout fix)."""

    def setUp(self):
        self.branch = Branch.objects.create(
            name='main',
            bitbake_branch='master',
            short_description='Main branch',
            sort_priority=1,
            hidden=False,
            updates_enabled=True,
        )

        # layer_a: base layer (type A), lower preference
        self.layer_a = LayerItem.objects.create(
            name='meta-alpha',
            status='P',
            layer_type='A',
            summary='Alpha layer',
            description='Alpha test layer',
            vcs_url='git://example.com/meta-alpha.git',
            index_preference=0,
        )
        # layer_b: software layer (type S), higher preference — recipes here win
        self.layer_b = LayerItem.objects.create(
            name='meta-beta',
            status='P',
            layer_type='S',
            summary='Beta layer',
            description='Beta test layer',
            vcs_url='git://example.com/meta-beta.git',
            index_preference=10,
        )
        # layer_c: unique objects only, should never appear as duplicates
        self.layer_c = LayerItem.objects.create(
            name='meta-gamma',
            status='P',
            layer_type='S',
            summary='Gamma layer',
            description='Gamma test layer',
            vcs_url='git://example.com/meta-gamma.git',
            index_preference=5,
        )

        self.lb_a = LayerBranch.objects.create(layer=self.layer_a, branch=self.branch)
        self.lb_b = LayerBranch.objects.create(layer=self.layer_b, branch=self.branch)
        self.lb_c = LayerBranch.objects.create(layer=self.layer_c, branch=self.branch)

        # Duplicate recipe in both layer_a (pref=0) and layer_b (pref=10)
        self.recipe_a = Recipe.objects.create(
            layerbranch=self.lb_a, filename='shared_1.0.bb',
            pn='shared', pv='1.0', filepath='recipes-test')
        self.recipe_b = Recipe.objects.create(
            layerbranch=self.lb_b, filename='shared_1.0.bb',
            pn='shared', pv='1.0', filepath='recipes-test')
        # Unique recipe only in layer_c — must NOT appear
        Recipe.objects.create(
            layerbranch=self.lb_c, filename='unique_1.0.bb',
            pn='unique', pv='1.0', filepath='recipes-test')

        # Duplicate class in layer_a and layer_b
        BBClass.objects.create(layerbranch=self.lb_a, name='sharedclass')
        BBClass.objects.create(layerbranch=self.lb_b, name='sharedclass')
        # Unique class only in layer_c — must NOT appear
        BBClass.objects.create(layerbranch=self.lb_c, name='uniqueclass')

        # Duplicate include file in layer_a and layer_b
        IncFile.objects.create(layerbranch=self.lb_a, path='conf/shared.inc')
        IncFile.objects.create(layerbranch=self.lb_b, path='conf/shared.inc')
        # Unique include file only in layer_c — must NOT appear
        IncFile.objects.create(layerbranch=self.lb_c, path='conf/unique.inc')

    def _url(self, branch='main'):
        return reverse('duplicates', kwargs={'branch': branch})

    # --- Basic page health ---

    def test_duplicates_view_returns_200(self):
        """DuplicatesView should return HTTP 200."""
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)

    # --- Recipes ---

    def test_duplicate_recipes_included(self):
        """Recipes appearing in more than one layer should be in context."""
        response = self.client.get(self._url())
        pns = [r.pn for r in response.context['recipes']]
        self.assertIn('shared', pns)

    def test_unique_recipes_excluded(self):
        """Recipes appearing in only one layer should not appear."""
        response = self.client.get(self._url())
        pns = [r.pn for r in response.context['recipes']]
        self.assertNotIn('unique', pns)

    def test_duplicate_recipes_have_two_rows(self):
        """Each layer's copy of the duplicate recipe should be present."""
        response = self.client.get(self._url())
        shared = [r for r in response.context['recipes'] if r.pn == 'shared']
        self.assertEqual(len(shared), 2)

    # --- preferred_count (batch MAX computation, replaces per-row correlated subquery) ---

    def test_lower_preference_recipe_is_deemphasised(self):
        """The layer_a recipe (pref=0) should have preferred_count > 0 because
        layer_b (pref=10, type S) has a higher-preference copy of the same pn."""
        response = self.client.get(self._url())
        recipe_from_a = next(
            r for r in response.context['recipes']
            if r.pn == 'shared' and r.layerbranch.layer.name == 'meta-alpha')
        self.assertGreater(recipe_from_a.preferred_count, 0)

    def test_higher_preference_recipe_is_not_deemphasised(self):
        """The layer_b recipe (pref=10) should have preferred_count == 0 because
        no other S/A layer has a higher preference for the same pn."""
        response = self.client.get(self._url())
        recipe_from_b = next(
            r for r in response.context['recipes']
            if r.pn == 'shared' and r.layerbranch.layer.name == 'meta-beta')
        self.assertEqual(recipe_from_b.preferred_count, 0)

    def test_preferred_count_attribute_present_on_all_recipes(self):
        """Every recipe in the context must have a preferred_count attribute."""
        response = self.client.get(self._url())
        for recipe in response.context['recipes']:
            self.assertTrue(hasattr(recipe, 'preferred_count'),
                            f"preferred_count missing on {recipe.pn}")

    # --- Classes ---

    def test_duplicate_classes_included(self):
        """Classes appearing in more than one layer should be in context."""
        response = self.client.get(self._url())
        names = [c.name for c in response.context['classes']]
        self.assertIn('sharedclass', names)

    def test_unique_classes_excluded(self):
        """Classes appearing in only one layer should not appear."""
        response = self.client.get(self._url())
        names = [c.name for c in response.context['classes']]
        self.assertNotIn('uniqueclass', names)

    def test_duplicate_classes_have_two_rows(self):
        """Both layer entries for the duplicate class should be present."""
        response = self.client.get(self._url())
        shared = [c for c in response.context['classes'] if c.name == 'sharedclass']
        self.assertEqual(len(shared), 2)

    # --- Include files ---

    def test_duplicate_incfiles_included(self):
        """Include files appearing in more than one layer should be in context."""
        response = self.client.get(self._url())
        paths = [f.path for f in response.context['incfiles']]
        self.assertIn('conf/shared.inc', paths)

    def test_unique_incfiles_excluded(self):
        """Include files appearing in only one layer should not appear."""
        response = self.client.get(self._url())
        paths = [f.path for f in response.context['incfiles']]
        self.assertNotIn('conf/unique.inc', paths)

    def test_duplicate_incfiles_have_two_rows(self):
        """Both layer entries for the duplicate include file should be present."""
        response = self.client.get(self._url())
        shared = [f for f in response.context['incfiles'] if f.path == 'conf/shared.inc']
        self.assertEqual(len(shared), 2)

    # --- Layer filter ---

    def test_layer_filter_restricts_recipes(self):
        """With only one layer selected, nothing can be a duplicate."""
        response = self.client.get(self._url() + f'?l={self.layer_a.id}')
        self.assertEqual(response.status_code, 200)
        pns = [r.pn for r in response.context['recipes']]
        self.assertNotIn('shared', pns)

    def test_wrong_branch_returns_empty(self):
        """A branch with no data should return empty result sets."""
        Branch.objects.create(name='other', bitbake_branch='other', sort_priority=50)
        response = self.client.get(reverse('duplicates', kwargs={'branch': 'other'}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(list(response.context['recipes'])), 0)
        self.assertEqual(len(list(response.context['classes'])), 0)
        self.assertEqual(len(list(response.context['incfiles'])), 0)

    def test_select_related_avoids_extra_queries(self):
        """Accessing layerbranch.layer.name after list evaluation fires no new queries."""
        from django.db import connection, reset_queries
        from django.conf import settings
        import layerindex.views as views_module

        settings.DEBUG = True
        reset_queries()

        v = views_module.DuplicatesView()
        v.kwargs = {'branch': 'main'}
        v.request = type('req', (), {'GET': {}})()

        recipes = v.get_recipes([])
        classes = list(v.get_classes([]))
        incfiles = list(v.get_incfiles([]))

        query_count_after_fetch = len(connection.queries)

        for r in recipes:
            _ = r.layerbranch.layer.name
        for c in classes:
            _ = c.layerbranch.layer.name
        for f in incfiles:
            _ = f.layerbranch.layer.name

        query_count_after_access = len(connection.queries)
        settings.DEBUG = False

        self.assertEqual(query_count_after_fetch, query_count_after_access,
                         "Extra queries fired when accessing layerbranch.layer.name — "
                         "select_related may not be effective")
