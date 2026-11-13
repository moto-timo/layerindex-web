# layerindex-web - tests for the Celery tasks in layerindex/tasks.py
#
# The tasks run in-process with apply(), so no broker is needed.
#
# Licensed under the MIT license, see COPYING.MIT for details
#
# SPDX-License-Identifier: MIT

from datetime import datetime

import pytest

from layerindex import tasks
from layerindex.models import Update


def test_send_email(mailoutbox):
    result = tasks.send_email.apply(('Subject', 'Body', 'from@example.com', ['to@example.com']))
    assert result.successful()
    assert len(mailoutbox) == 1
    msg = mailoutbox[0]
    assert (msg.subject, msg.body, msg.from_email, msg.to) == ('Subject', 'Body', 'from@example.com', ['to@example.com'])


@pytest.mark.django_db
@pytest.mark.parametrize('command, retcode, log', [
    ('echo update %update% on %branch%', 0, 'update {id} on master'),
    ('echo failed; exit 3', 3, 'failed'),
])
def test_run_update_command(settings, tmp_path, command, retcode, log):
    settings.TASK_LOG_DIR = str(tmp_path / 'logs')
    update = Update.objects.create(started=datetime.now(), task_id='test-task')
    result = tasks.run_update_command.apply(('master', command), task_id='test-task')
    assert result.get()['retcode'] == retcode
    update.refresh_from_db()
    assert update.retcode == retcode
    assert update.log == log.format(id=update.id)
    assert update.finished is not None
    assert (tmp_path / 'logs' / 'task_test-task.log').exists()
