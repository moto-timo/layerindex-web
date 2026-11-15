# layerindex-web - recipe search ignores case on any database
#
# Licensed under the MIT license, see COPYING.MIT for details
#
# SPDX-License-Identifier: MIT

# MariaDB compares strings without case (utf8mb4_unicode_ci); PostgreSQL
# doesn't, so the search has to ask for it. Some recipe names have capitals,
# e.g. python3-cherryPy.

import pytest
from django.urls import reverse

from layerindex.models import Branch, LayerBranch, LayerItem, Recipe

pytestmark = pytest.mark.django_db


@pytest.fixture
def recipes():
    branch = Branch.objects.get(name='master')
    layer = LayerItem.objects.create(name='meta-Test', status='P', layer_type='S',
                                     summary='Test', description='Test',
                                     vcs_url='git://example.com/meta-test.git')
    lb = LayerBranch.objects.create(layer=layer, branch=branch)
    cherrypy = Recipe.objects.create(layerbranch=lb, filename='cherryPy_1.0.bb', pn='cherryPy',
                                     pv='1.0', filepath='recipes-test', summary='A web framework')
    other = Recipe.objects.create(layerbranch=lb, filename='cherrypy-tools_1.0.bb',
                                  pn='cherrypy-tools', pv='1.0', filepath='recipes-test',
                                  summary='Tools for cherryPy')
    # The same recipe in another layer, so that a layer: filter that matches
    # nothing doesn't still leave a single result
    layer2 = LayerItem.objects.create(name='meta-other', status='P', layer_type='S',
                                      summary='Other', description='Other',
                                      vcs_url='git://example.com/meta-other.git')
    lb2 = LayerBranch.objects.create(layer=layer2, branch=branch)
    Recipe.objects.create(layerbranch=lb2, filename='cherrypy-tools_1.0.bb', pn='cherrypy-tools',
                          pv='1.0', filepath='recipes-test', summary='Tools for cherryPy')
    # Sorts before "Zope" by name, so comes first unless the exact match is
    Recipe.objects.create(layerbranch=lb, filename='azope-extra_1.0.bb', pn='azope-extra',
                          pv='1.0', filepath='recipes-test', summary='Extras')
    Recipe.objects.create(layerbranch=lb, filename='Zope_1.0.bb', pn='Zope',
                          pv='1.0', filepath='recipes-test', summary='An application server')
    return cherrypy, other


def search(client, q):
    return client.get(reverse('recipe_search', args=('master',)), {'q': q})


def test_pn_prefix_ignores_case(client, recipes):
    response = search(client, 'pn:cherrypy')
    # A single result redirects to the recipe
    assert response.status_code == 302
    assert response.url == reverse('recipe', args=(recipes[0].id,))


def test_layer_prefix_ignores_case(client, recipes):
    response = search(client, 'layer:meta-test cherrypy-tools')
    assert response.status_code == 302
    assert response.url == reverse('recipe', args=(recipes[1].id,))


def test_exact_name_first_ignores_case(client, recipes):
    response = search(client, 'zope')
    assert response.status_code == 200
    assert [r.pn for r in response.context['recipe_list']] == ['Zope', 'azope-extra']
