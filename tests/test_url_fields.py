# layerindex-web - URL form fields use https for a URL entered without a scheme
#
# Licensed under the MIT license, see COPYING.MIT for details
#
# SPDX-License-Identifier: MIT

import importlib
import warnings

from django import forms
from django.contrib import admin
from django.utils.deprecation import RemovedInDjango60Warning

import layerindex.forms
from layerindex.models import LayerItem


def test_url_form_fields_assume_https(rf, admin_user):
    # [YOCTO #16498] create the form classes again, to see any warning
    with warnings.catch_warnings():
        warnings.simplefilter('error', RemovedInDjango60Warning)
        mod = importlib.reload(layerindex.forms)
        request = rf.get('/')
        request.user = admin_user
        admin_form = admin.site._registry[LayerItem].get_form(request)

    url_fields = [
        mod.EditLayerForm.base_fields['vcs_web_url'],
        mod.EditLayerForm.base_fields['mailing_list_url'],
        mod.BulkChangeEditForm.base_fields['homepage'],
        mod.BulkChangeEditForm.base_fields['bugtracker'],
        admin_form.base_fields['vcs_web_url'],
    ]
    for field in url_fields:
        assert isinstance(field, forms.URLField)
        assert field.clean('github.com/example/meta-example') == 'https://github.com/example/meta-example'
