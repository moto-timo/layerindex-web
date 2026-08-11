#!/usr/bin/env python3

# layerindex-web - scan for case-variant duplicate values in unique fields
#
# Run this against the MariaDB source database BEFORE migrating to
# PostgreSQL. MariaDB's default collation (utf8mb4_unicode_ci) makes
# uniqueness case-insensitive; PostgreSQL's default collation is
# case-sensitive. Any pair of values that differ only in case would have
# been rejected as a duplicate under MariaDB but could both exist as
# separate rows there if inserted through means that bypassed the unique
# constraint (e.g. bulk loading) - this script surfaces such pairs before
# they cause problems post-migration (or just to confirm there are none).
#
# Licensed under the MIT license, see COPYING.MIT for details
#
# SPDX-License-Identifier: MIT

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')
django.setup()

from django.apps import apps
from django.db.models import CharField, TextField


def find_unique_text_fields():
    fields = []
    for model in apps.get_models():
        for field in model._meta.get_fields():
            if isinstance(field, (CharField, TextField)) and getattr(field, 'unique', False):
                fields.append((model, field.name))
    return fields


def find_case_duplicates(model, field_name):
    seen = {}
    dupes = []
    qs = model.objects.values_list('pk', field_name).order_by(field_name)
    for pk, value in qs:
        if value is None:
            continue
        key = value.lower()
        if key in seen:
            dupes.append((seen[key], (pk, value)))
        else:
            seen[key] = (pk, value)
    return dupes


def main():
    fields = find_unique_text_fields()
    found_any = False
    for model, field_name in fields:
        dupes = find_case_duplicates(model, field_name)
        if dupes:
            found_any = True
            print(f'{model.__name__}.{field_name}:')
            for (pk1, val1), (pk2, val2) in dupes:
                print(f'  pk={pk1} {val1!r}  vs  pk={pk2} {val2!r}')
    if not found_any:
        print('No case-variant duplicates found in any unique text field.')
        return 0
    else:
        print()
        print('Resolve the above before migrating to PostgreSQL - PostgreSQL')
        print('uniqueness is case-sensitive and these rows will otherwise be')
        print('treated as distinct, which may not match prior MariaDB behavior.')
        return 1


if __name__ == '__main__':
    sys.exit(main())
