# layerindex-web - test that indexing a distro configuration file doesn't
# change the configuration used to parse recipes
#
# Licensed under the MIT license, see COPYING.MIT for details
#
# SPDX-License-Identifier: MIT

import os
import sys
import types

import pytest

basepath = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


@pytest.fixture
def bb_data(settings):
    from layerindex.models import LayerItem
    bitbakepath = os.path.join(settings.LAYER_FETCH_DIR,
                               LayerItem(vcs_url=settings.BITBAKE_REPO_URL).get_fetch_dir())
    if not os.path.isdir(os.path.join(bitbakepath, 'lib', 'bb')):
        pytest.skip('BitBake not fetched to %s' % bitbakepath)
    for path in (os.path.join(bitbakepath, 'lib'), os.path.join(basepath, 'layerindex')):
        if path not in sys.path:
            sys.path.insert(0, path)
    import bb.data
    import bb.parse
    import utils
    utils.bb = sys.modules['bb']
    return bb.data


def test_distro_conf_not_parsed_into_recipe_data(bb_data, tmp_path):
    import update_layer
    conf = tmp_path / 'conf' / 'distro' / 'testdistro.conf'
    conf.parent.mkdir(parents=True)
    conf.write_text('DISTRO_NAME = "Test Distro"\nLEAKCHECK = "from the distro"\n')
    d = bb_data.init()
    d.setVar('LEAKCHECK', 'original')
    distro = types.SimpleNamespace(description='')

    update_layer.update_distro_conf_file(str(conf), distro, d)

    assert distro.description == 'Test Distro'
    # Recipes parsed with d afterwards must not see the distro's settings
    assert d.getVar('LEAKCHECK') == 'original'
