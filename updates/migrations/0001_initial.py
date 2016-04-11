# -*- coding: utf-8 -*-
# Generated by Django 1.9 on 2016-01-19 05:16
from __future__ import unicode_literals

from django.conf import settings
import django.contrib.postgres.fields
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Team',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=25, unique=True)),
                ('description', models.TextField(blank=True)),
                ('email', models.EmailField(max_length=254, unique=True)),
                ('digest_days_sent', django.contrib.postgres.fields.ArrayField(base_field=models.IntegerField(validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(6)]), default=[], size=7)),
                ('send_digest_at', models.TimeField()),
                ('send_reminders_at', models.TimeField()),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]