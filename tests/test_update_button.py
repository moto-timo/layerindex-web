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


@pytest.mark.django_db
@pytest.mark.parametrize('finished, retcode, done, result', [
    (False, 0, '0', None),
    (True, 0, '1', '0'),
    (True, 2, '1', '2'),
])
def test_task_log_reports_status_from_update(client, django_user_model, settings, tmp_path,
                                             finished, retcode, done, result):
    settings.TASK_LOG_DIR = str(tmp_path)
    (tmp_path / 'task_test-task.log').write_text('line 1 <b>\n', encoding='utf-8')
    Update.objects.create(started=datetime.now(), task_id='test-task', retcode=retcode,
                          finished=datetime.now() if finished else None)
    client.force_login(django_user_model.objects.create_user('user', 'user@example.com', 'pw'))

    response = client.get(reverse('task_log', args=('test-task',)))

    assert response.status_code == 200
    assert response.content == b'line 1 &lt;b&gt;\n'
    assert response['Task-Done'] == done
    assert response.get('Task-Result') == result
