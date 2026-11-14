# layerindex-web - test the layer page of a layer that has not been indexed
#
# Licensed under the MIT license, see COPYING.MIT for details
#
# SPDX-License-Identifier: MIT

from datetime import datetime

import pytest
from django.urls import reverse

from layerindex.models import Branch, LayerBranch, LayerItem, LayerUpdate, Update


@pytest.fixture
def new_layer(db):
    master, _ = Branch.objects.get_or_create(name='master', defaults={'bitbake_branch': 'master'})
    layer = LayerItem.objects.create(name='meta-new', status='P', layer_type='A', summary='new',
                                     description='new', vcs_url='git://example.com/meta-new.git')
    LayerBranch.objects.create(layer=layer, branch=master)
    return layer


def add_update(layer, log):
    update = Update.objects.create(started=datetime.now(), finished=datetime.now())
    layerupdate = LayerUpdate(update=update, layer=layer, branch=Branch.objects.get(name='master'),
                              started=datetime.now(), finished=datetime.now(), log=log)
    layerupdate.save()
    return layerupdate


@pytest.mark.django_db
def test_failed_first_parse_shows_warning(client, new_layer):
    # [YOCTO #13489]
    layerupdate = add_update(new_layer, 'ERROR: conf/layer.conf not found for layer meta-new')
    page = client.get(reverse('layer_item', args=('master', 'meta-new'))).content.decode()
    assert 'could not be indexed' in page
    assert reverse('layerupdate', args=(layerupdate.id,)) in page
    assert 'has not yet been indexed' not in page


@pytest.mark.django_db
def test_not_yet_indexed(client, new_layer):
    for log in (None, 'WARNING: something'):
        if log:
            add_update(new_layer, log)
        page = client.get(reverse('layer_item', args=('master', 'meta-new'))).content.decode()
        assert 'has not yet been indexed' in page
        assert 'could not be indexed' not in page
