# layerindex-web - tests for the raw SQL queries in rrs/views.py
#
# Licensed under the MIT license, see COPYING.MIT for details
#
# SPDX-License-Identifier: MIT

# The queries run against the test database, so they are checked on both
# PostgreSQL and MariaDB. They need the rrs app (ENABLE_RRS=1).

from datetime import datetime

import pytest
from django.conf import settings

pytestmark = [
    pytest.mark.skipif('rrs' not in settings.INSTALLED_APPS, reason='needs ENABLE_RRS=1'),
    pytest.mark.django_db,
]


def dt(day):
    # USE_TZ is False: the database stores naive datetimes
    return datetime(2026, 11, day)


@pytest.fixture
def data():
    from layerindex.models import Branch, LayerBranch, LayerItem
    from rrs.models import (
        Maintainer,
        RecipeMaintainer,
        RecipeMaintainerHistory,
        RecipeSymbol,
        RecipeUpgrade,
        RecipeUpstream,
        RecipeUpstreamHistory,
    )

    branch = Branch.objects.get(name='master')
    layer = LayerItem.objects.create(name='meta-test', status='P', layer_type='A',
                                     summary='Test', description='Test',
                                     vcs_url='git://example.com/meta-test.git')
    lb = LayerBranch.objects.create(layer=layer, branch=branch)
    alice = Maintainer.objects.create(name='Alice')
    bob = Maintainer.objects.create(name='Bob')
    foo = RecipeSymbol.objects.create(layerbranch=lb, pn='foo', summary='Foo')
    bar = RecipeSymbol.objects.create(layerbranch=lb, pn='bar', summary='Bar')
    mhist = RecipeMaintainerHistory.objects.create(date=dt(2), author=alice, sha1='a' * 40,
                                                   layerbranch=lb)
    RecipeMaintainer.objects.create(recipesymbol=foo, maintainer=alice, history=mhist)
    RecipeMaintainer.objects.create(recipesymbol=bar, maintainer=bob, history=mhist)
    uhist = RecipeUpstreamHistory.objects.create(layerbranch=lb, start_date=dt(3), end_date=dt(3))
    RecipeUpstream.objects.create(recipesymbol=foo, history=uhist, version='2.0', status='Y',
                                  date=dt(3))
    RecipeUpstream.objects.create(recipesymbol=bar, history=uhist, version='3.0', status='N',
                                  date=dt(3))
    for symbol, version, day in ((foo, '1.0', 1), (foo, '2.0', 4), (bar, '1.5', 1)):
        RecipeUpgrade.objects.create(recipesymbol=symbol, version=version, author_date=dt(day),
                                     commit_date=dt(day), upgrade_type='U')
    return {'lb': lb, 'foo': foo, 'bar': bar, 'mhist': mhist, 'uhist': uhist}


def test_maintainers_by_recipes(data):
    from rrs.views import Raw
    ids = [data['foo'].id, data['bar'].id]
    rows = Raw.get_ma_by_recipes_and_date(ids, data['mhist'].id)
    assert sorted((r['recipesymbol_id'], r['name']) for r in rows) == \
        sorted([(data['foo'].id, 'Alice'), (data['bar'].id, 'Bob')])
    assert Raw.get_ma_by_recipes_and_date([], data['mhist'].id) == []
    assert Raw.get_re_by_mantainer_and_date('Bob', data['mhist'].id) == [data['bar'].id]


def test_upstream_by_recipes(data):
    from rrs.views import Raw
    rows = Raw.get_reup_by_recipes_and_date([data['foo'].id, data['bar'].id], data['uhist'].id)
    assert sorted((r['recipesymbol_id'], r['status'], r['version']) for r in rows) == \
        sorted([(data['foo'].id, 'Y', '2.0'), (data['bar'].id, 'N', '3.0')])
    assert Raw.get_reup_by_recipes_and_date([], data['uhist'].id) == []
    assert Raw.get_reup_by_date(data['uhist'].id) == [data['bar'].id]


def test_upgrades(data):
    from rrs.views import Raw
    lb = data['lb'].id
    # The latest upgrade of each recipe up to the date
    rows = Raw.get_reupg_by_date(lb, dt(3))
    assert [(r['pn'], r['version']) for r in rows] == [('bar', '1.5'), ('foo', '1.0')]
    rows = Raw.get_reupg_by_date(lb, dt(5))
    assert [(r['pn'], r['version']) for r in rows] == [('bar', '1.5'), ('foo', '2.0')]
    rows = Raw.get_reup_by_last_updated(lb, dt(5))
    assert {r['recipesymbol_id']: r['date'] for r in rows} == {data['foo'].id: dt(4),
                                                               data['bar'].id: dt(1)}
    rows = Raw.get_reupg_by_dates_and_recipes(dt(2), dt(5), [data['foo'].id, data['bar'].id])
    assert [r['recipesymbol_id'] for r in rows] == [data['foo'].id]
    assert Raw.get_reupg_by_dates_and_recipes(dt(2), dt(5), []) == []
    assert Raw.get_remahi_by_end_date(lb, dt(5)) == (data['mhist'].id,)


def test_upstream_statistics(data):
    from rrs.models import MaintenancePlan, MaintenancePlanLayerBranch
    from rrs.views import Raw
    plan = MaintenancePlan.objects.create(name='Test')
    MaintenancePlanLayerBranch.objects.create(plan=plan, layerbranch=data['lb'])
    # foo is up to date, bar is not
    assert Raw.get_reup_statistics(plan, dt(5), data['uhist']) == (1, 1, 0, 0)
