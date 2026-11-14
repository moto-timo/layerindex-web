# layerindex-web - tests for updating layer dependencies from conf/layer.conf
#
# Licensed under the MIT license, see COPYING.MIT for details
#
# SPDX-License-Identifier: MIT

import logging
import types

import pytest

from layerindex import utils
from layerindex.models import Branch, LayerBranch, LayerDependency, LayerItem

LOG = logging.getLogger('test')


@pytest.fixture
def fake_bb(monkeypatch):
    """BitBake is only importable during a real update; parse LAYERDEPENDS
    without version constraints, which is all these tests use."""
    bb = types.SimpleNamespace(utils=types.SimpleNamespace(
        VersionStringException=Exception,
        explode_dep_versions2=lambda s: {d: [] for d in s.split()}))
    monkeypatch.setattr(utils, 'bb', bb, raising=False)


class FakeConfig:
    def __init__(self, **values):
        self.values = values

    def getVar(self, name, expand=True):
        return self.values.get(name)


@pytest.fixture
def layers(db):
    master, _ = Branch.objects.get_or_create(name='master', defaults={'bitbake_branch': 'master'})
    lbs = {}
    for name in ('meta-arm-bsp', 'meta-arm', 'meta-linux-mainline', 'meta-manual', 'meta-gone'):
        layer = LayerItem.objects.create(name=name, status='P', layer_type='A', summary=name,
                                         description=name, vcs_url='git://example.com/%s.git' % name)
        lbs[name] = LayerBranch.objects.create(layer=layer, branch=master, collection=name)
    return lbs


def deps(lb):
    return {d.dependency.name: d.from_layer_conf for d in LayerDependency.objects.filter(layerbranch=lb)}


def add(lb, name):
    LayerDependency.objects.create(layerbranch=lb, dependency=LayerItem.objects.get(name=name))


@pytest.mark.django_db
def test_dependency_dropped_from_layer_conf_is_removed(fake_bb, layers):
    lb = layers['meta-arm-bsp']
    utils.add_dependencies(lb, FakeConfig(**{'LAYERDEPENDS_meta-arm-bsp': 'meta-arm meta-linux-mainline'}), logger=LOG)
    assert deps(lb) == {'meta-arm': True, 'meta-linux-mainline': True}

    # [YOCTO #14348] meta-arm-bsp stopped depending on meta-linux-mainline
    utils.add_dependencies(lb, FakeConfig(**{'LAYERDEPENDS_meta-arm-bsp': 'meta-arm'}), logger=LOG)
    assert deps(lb) == {'meta-arm': True}


@pytest.mark.django_db
def test_dependencies_added_by_hand_are_kept(fake_bb, layers, caplog):
    lb = layers['meta-arm-bsp']
    add(lb, 'meta-manual')
    add(lb, 'meta-arm')   # also in conf/layer.conf: recorded as such

    with caplog.at_level(logging.WARNING):
        utils.add_dependencies(lb, FakeConfig(**{'LAYERDEPENDS_meta-arm-bsp': 'meta-arm'}), logger=LOG)

    assert deps(lb) == {'meta-arm': True, 'meta-manual': False}
    assert 'LAYERDEPENDS meta-manual of meta-arm-bsp are not in its conf/layer.conf' in caplog.text


@pytest.mark.django_db
def test_unresolvable_dependency_is_kept(fake_bb, layers):
    lb = layers['meta-arm-bsp']
    utils.add_dependencies(lb, FakeConfig(**{'LAYERDEPENDS_meta-arm-bsp': 'meta-gone'}), logger=LOG)
    # meta-gone has no branch here any more, but conf/layer.conf still names it
    LayerBranch.objects.filter(layer__name='meta-gone').delete()
    utils.add_dependencies(lb, FakeConfig(**{'LAYERDEPENDS_meta-arm-bsp': 'meta-gone'}), logger=LOG)
    assert deps(lb) == {'meta-gone': True}


@pytest.mark.django_db
def test_all_dependencies_dropped_from_layer_conf(fake_bb, layers):
    lb = layers['meta-arm-bsp']
    add(lb, 'meta-manual')
    utils.add_dependencies(lb, FakeConfig(**{'LAYERDEPENDS_meta-arm-bsp': 'meta-arm'}), logger=LOG)
    utils.add_dependencies(lb, FakeConfig(), logger=LOG)
    assert deps(lb) == {'meta-manual': False}


@pytest.mark.django_db
def test_remove_layer_dependencies_setting_removes_all(fake_bb, layers, settings):
    settings.REMOVE_LAYER_DEPENDENCIES = True
    lb = layers['meta-arm-bsp']
    add(lb, 'meta-manual')
    utils.add_dependencies(lb, FakeConfig(**{'LAYERDEPENDS_meta-arm-bsp': 'meta-arm'}), logger=LOG)
    assert deps(lb) == {'meta-arm': True}
