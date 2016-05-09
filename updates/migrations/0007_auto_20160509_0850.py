# -*- coding: utf-8 -*-
# Generated by Django 1.9 on 2016-05-09 08:50
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('updates', '0006_inboundwebhookrequest'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='membership',
            name='role',
        ),
        migrations.AddField(
            model_name='membership',
            name='is_active',
            field=models.BooleanField(default=True, verbose_name='Active'),
        ),
        migrations.AddField(
            model_name='update',
            name='blocker',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='update',
            name='done',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='update',
            name='will_do',
            field=models.TextField(blank=True),
        ),
    ]