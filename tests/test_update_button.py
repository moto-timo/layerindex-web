# layerindex-web - tests for the Update Layer button and its task status page
#
# Licensed under the MIT license, see COPYING.MIT for details
#
# SPDX-License-Identifier: MIT

from datetime import datetime

import pytest
from django.urls import reverse

from layerindex import tasks, views
from layerindex.models import Branch, LayerBranch, LayerItem, Update


@pytest.fixture
def staff_client(client, django_user_model):
    user = django_user_model.objects.create_user('staff', 'staff@example.com', 'pw', is_staff=True)
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_update_layer_creates_one_update(staff_client, monkeypatch):
    branch, _ = Branch.objects.get_or_create(name='master', defaults={'bitbake_branch': 'master'})
    layer = LayerItem.objects.create(name='meta-test', status='P', layer_type='A',
                                     summary='test', description='test',
                                     vcs_url='git://example.com/meta-test.git')
    LayerBranch.objects.create(layer=layer, branch=branch)
    queued = []
    monkeypatch.setattr(views.tasks.run_update_command, 'apply_async',
                        lambda args, task_id: queued.append((args, task_id)))
    before = Update.objects.count()

    response = staff_client.get(reverse('update_layer', args=('master', 'meta-test')))

    assert response.status_code == 302
    (branch_name, cmd), task_id = queued[0]
    assert Update.objects.count() == before + 1
    assert Update.objects.filter(task_id=task_id).exists()
    # update.py records its work in the view's Update rather than a new one
    assert '--update %update%' in cmd


@pytest.mark.django_db
def test_run_update_command_keeps_fields_set_by_command(settings, tmp_path, monkeypatch):
    settings.TASK_LOG_DIR = str(tmp_path)
    update = Update.objects.create(started=datetime.now(), task_id='test-task')

    def fake_runcmd(cmd, destdir, outfile, shell):
        # Stands in for update.py --update, writing to the same record
        assert cmd == 'update.py --update %d' % update.id
        Update.objects.filter(id=update.id).update(reload=True)
        return 'output'
    monkeypatch.setattr(tasks.utils, 'runcmd', fake_runcmd)

    tasks.run_update_command.apply(('master', 'update.py --update %update%'), task_id='test-task')

    update.refresh_from_db()
    assert update.reload
    assert (update.log, update.retcode) == ('output', 0)
    assert update.finished is not None
