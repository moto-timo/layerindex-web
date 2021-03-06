# -*- coding: utf-8 -*-
# Generated by Django 1.11.12 on 2018-08-13 23:06
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('layerindex', '0022_layerupdate_set_layer_branch'),
    ]

    operations = [
        migrations.AlterField(
            model_name='layerupdate',
            name='branch',
            field=models.ForeignKey(on_delete=models.deletion.CASCADE, to='layerindex.Branch'),
        ),
        migrations.AlterField(
            model_name='layerupdate',
            name='layer',
            field=models.ForeignKey(on_delete=models.deletion.CASCADE, to='layerindex.LayerItem'),
        ),
        migrations.RemoveField(
            model_name='layerupdate',
            name='layerbranch',
        ),
    ]
