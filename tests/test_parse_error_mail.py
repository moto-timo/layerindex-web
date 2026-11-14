# layerindex-web - tests for the parse error emails to maintainers
#
# Licensed under the MIT license, see COPYING.MIT for details
#
# SPDX-License-Identifier: MIT

import logging
from datetime import datetime, timedelta

import pytest
from django.contrib.auth.models import User
from django.core import mail

from layerindex.models import (Branch, LayerBranch, LayerItem, LayerMaintainer, LayerUpdate, Update,
                               UserProfile)
from layerindex.notify import notify_parse_errors

LOG = logging.getLogger('test')
START = datetime(2026, 11, 1)


def make_layers(names):
    master, _ = Branch.objects.get_or_create(name='master', defaults={'bitbake_branch': 'master'})
    layers = {}
    for name in names:
        layer = LayerItem.objects.create(name=name, status='P', layer_type='A', summary=name,
                                         description=name, vcs_url='git://example.com/%s.git' % name)
        LayerBranch.objects.create(layer=layer, branch=master)
        layers[name] = layer
    return layers


def run_update(layers, failing, day):
    update = Update.objects.create(started=START + timedelta(days=day), finished=START + timedelta(days=day))
    for name, layer in layers.items():
        lu = LayerUpdate(update=update, layer=layer, branch=Branch.objects.get(name='master'),
                         started=START + timedelta(days=day), log='ERROR: broken\n' if name in failing else '')
        lu.save()
    return update


def subscribe(username, email, notify=True, active=True):
    user = User.objects.create_user(username, email, 'pw', is_active=active)
    UserProfile.objects.create(user=user, notify_parse_errors=notify)


@pytest.mark.django_db
def test_maintainers_who_opted_in_get_mail_when_a_layer_starts_failing():
    # [YOCTO #11196]
    layers = make_layers(['meta-a', 'meta-b'])
    lb = layers['meta-a'].layerbranch_set.get()
    for name, email, status in (('Yes', 'Yes@example.com', 'A'), ('No', 'no@example.com', 'A'),
                                ('Gone', 'gone@example.com', 'I')):
        LayerMaintainer.objects.create(layerbranch=lb, name=name, email=email, status=status)
    subscribe('yes', 'yes@example.com')
    subscribe('no', 'no@example.com', notify=False)
    subscribe('gone', 'gone@example.com')

    run_update(layers, [], day=0)
    notify_parse_errors(run_update(layers, ['meta-a'], day=1), LOG)
    assert [m.to for m in mail.outbox] == [['yes@example.com']]
    assert 'meta-a (master) failed to parse' in mail.outbox[0].subject
    assert '/layerindex/layerupdate/' in mail.outbox[0].body

    # Still failing: no new mail
    mail.outbox.clear()
    notify_parse_errors(run_update(layers, ['meta-a'], day=2), LOG)
    assert mail.outbox == []


@pytest.mark.django_db
def test_mass_failure_goes_to_the_admins(settings):
    settings.ADMINS = [('Admin', 'admin@example.com')]
    layers = make_layers(['meta-%d' % i for i in range(10)])
    for layer in layers.values():
        LayerMaintainer.objects.create(layerbranch=layer.layerbranch_set.get(), name='M', email='m@example.com')
    subscribe('m', 'm@example.com')

    run_update(layers, [], day=0)
    notify_parse_errors(run_update(layers, list(layers)[:6], day=1), LOG)
    assert [m.to for m in mail.outbox] == [['admin@example.com']]
    assert '6 of 10 layer branches newly failed' in mail.outbox[0].subject
