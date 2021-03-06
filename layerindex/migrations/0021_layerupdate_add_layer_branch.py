# -*- coding: utf-8 -*-
# Generated by Django 1.11.12 on 2018-08-13 22:44
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('layerindex', '0020_update_manual'),
    ]

    operations = [
        migrations.AddField(
            model_name='layerupdate',
            name='branch',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='layerindex.Branch'),
        ),
        migrations.AddField(
            model_name='layerupdate',
            name='layer',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='layerindex.LayerItem'),
        ),
    ]
