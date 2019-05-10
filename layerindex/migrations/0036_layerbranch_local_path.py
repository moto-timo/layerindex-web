# -*- coding: utf-8 -*-
# Generated by Django 1.11.16 on 2019-04-02 20:22
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('layerindex', '0034_source_sha256sum'),
    ]

    operations = [
        migrations.AddField(
            model_name='layerbranch',
            name='local_path',
            field=models.CharField(blank=True, help_text='Local subdirectory where layer data can be found', max_length=255),
        ),
    ]