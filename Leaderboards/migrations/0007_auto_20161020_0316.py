# -*- coding: utf-8 -*-
# Generated by Django 1.10.1 on 2016-10-20 03:16
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Leaderboards', '0006_auto_20161020_0314'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='session',
            name='max_players',
        ),
        migrations.RemoveField(
            model_name='session',
            name='min_players',
        ),
        migrations.AddField(
            model_name='game',
            name='max_players',
            field=models.PositiveIntegerField(default=4, verbose_name='Maximum number of players'),
        ),
        migrations.AddField(
            model_name='game',
            name='min_players',
            field=models.PositiveIntegerField(default=2, verbose_name='Minimum number of players'),
        ),
    ]
