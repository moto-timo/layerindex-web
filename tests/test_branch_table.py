# layerindex-web - test the table of a layer's branches on the layer page
#
# Licensed under the MIT license, see COPYING.MIT for details
#
# SPDX-License-Identifier: MIT

import re
from datetime import datetime

import pytest
from django.urls import reverse

from layerindex.models import Branch, LayerBranch, LayerItem


@pytest.mark.django_db
def test_branch_table(client):
    # [YOCTO #15380] like meta-qt6, where each branch tracks a different git branch
    master, _ = Branch.objects.get_or_create(name='master', defaults={'bitbake_branch': 'master'})
    master.sort_priority = 1
    master.save()
    scarthgap = Branch.objects.create(name='scarthgap', bitbake_branch='2.8', sort_priority=2)
    kirkstone = Branch.objects.create(name='kirkstone', bitbake_branch='2.0', sort_priority=3,
                                      updates_enabled=False)
    hidden = Branch.objects.create(name='hiddenbranch', bitbake_branch='master', hidden=True)
    layer = LayerItem.objects.create(name='meta-qt', status='P', layer_type='S', summary='qt',
                                     description='qt', vcs_url='git://example.com/meta-qt.git')
    LayerBranch.objects.create(layer=layer, branch=master, actual_branch='dev',
                               vcs_last_commit=datetime(2026, 11, 1))
    LayerBranch.objects.create(layer=layer, branch=scarthgap, actual_branch='6.8')
    LayerBranch.objects.create(layer=layer, branch=kirkstone, actual_branch='6.2')
    LayerBranch.objects.create(layer=layer, branch=hidden)

    page = client.get(reverse('layer_item', args=('master', 'meta-qt'))).content.decode()
    table = page[page.index('id="branches"'):]
    rows = [re.sub(r'<[^>]+>|\s+', ' ', r).split() for r in re.findall(r'<tr>(.*?)</tr>', table, re.S)[1:]]

    assert [r[:2] for r in rows] == [['master', 'dev'], ['scarthgap', '6.8'], ['kirkstone', '6.2']]
    assert rows[0][2:] == ['2026-11-01', 'updated']
    assert rows[1][2:5] == ['not', 'indexed', 'updated']
    assert 'Updates are disabled for the kirkstone branch' in table
    assert 'hiddenbranch' not in table
    # The current branch is not a link; the others are
    assert reverse('layer_item', args=('scarthgap', 'meta-qt')) in table
    assert reverse('layer_item', args=('master', 'meta-qt')) not in table
