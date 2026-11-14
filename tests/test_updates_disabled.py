# layerindex-web - test the indication that a layer branch is no longer updated
#
# Licensed under the MIT license, see COPYING.MIT for details
#
# SPDX-License-Identifier: MIT

import pytest
from django.urls import reverse

from layerindex.models import Branch, LayerBranch, LayerItem


def make(name, status='P'):
    master, _ = Branch.objects.get_or_create(name='master', defaults={'bitbake_branch': 'master'})
    layer = LayerItem.objects.create(name=name, status=status, layer_type='A', summary=name,
                                     description=name, vcs_url='git://example.com/%s.git' % name)
    return LayerBranch.objects.create(layer=layer, branch=master)


@pytest.mark.django_db
def test_updates_disabled_reason():
    # [YOCTO #14781] updates can be off for the layer, the branch or the layer branch
    lb = make('meta-a')
    assert lb.updates_disabled_reason() == ''
    lb.updates_enabled = False
    assert lb.updates_disabled_reason() == 'Updates are disabled for this layer on the master branch'
    lb.branch.updates_enabled = False
    assert lb.updates_disabled_reason() == 'Updates are disabled for the master branch'
    lb.layer.status = 'X'
    assert lb.updates_disabled_reason() == 'Updates are disabled for this layer'


@pytest.mark.django_db
def test_not_updated_label_on_layer_pages(client):
    make('meta-updated')
    make('meta-stale', status='X')
    layers = client.get(reverse('layer_list', args=('master',))).content.decode()
    assert layers.count('>not updated</span>') == 1
    assert 'title="Updates are disabled for this layer"' in layers

    page = client.get(reverse('layer_item', args=('master', 'meta-stale'))).content.decode()
    assert 'not updated</span>' in page
    assert 'Updates are disabled for this layer, so the information here may be out of date.' in page
    page = client.get(reverse('layer_item', args=('master', 'meta-updated'))).content.decode()
    assert 'not updated</span>' not in page
