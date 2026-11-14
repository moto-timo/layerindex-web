# layerindex-web - test that the Celery worker can load the task module
#
# Licensed under the MIT license, see COPYING.MIT for details
#
# SPDX-License-Identifier: MIT

import os
import subprocess
import sys


def test_tasks_module_loads_without_django_settings_module():
    # As the worker does: celery --workdir=<source> --app layerindex.tasks
    env = {k: v for k, v in os.environ.items() if k != 'DJANGO_SETTINGS_MODULE'}
    srcdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = subprocess.run([sys.executable, '-c', 'import layerindex.tasks as t; print(t.tasks.conf.broker_url)'],
                            cwd=srcdir, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith('amqp://')
