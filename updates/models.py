from django.contrib.postgres.fields import ArrayField
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models

from timezone_field import TimeZoneField

from digestus.users.models import User


class Team(models.Model):
    name = models.CharField(max_length=25, unique=True)
    description = models.TextField(blank=True)
    email = models.EmailField(unique=True)
    created_by = models.ForeignKey(User)
    timezone = TimeZoneField(default='UTC')
    digest_days_sent = ArrayField(models.IntegerField(validators=[MinValueValidator(0),
                                                                  MaxValueValidator(6)]),
                                  size=7,
                                  default=[])
    send_digest_at = models.TimeField()
    send_reminders_at = models.TimeField()

    def __str__(self):
        return self.name


class Membership(models.Model):
    team = models.ForeignKey(Team, related_name='memberships')
    user = models.ForeignKey(User)
    role = models.CharField(max_length=25)

    class Meta:
        unique_together = (('team', 'user'),)

    def __str__(self):
        return '{} - {}'.format(self.team,
                                self.user.get_full_name())


class Update(models.Model):
    membership = models.ForeignKey(Membership, related_name='updates')
    for_date = models.DateField()

    def __str__(self):
        return '{} - {}'.format(self.membership.user.get_full_name(),
                                self.for_date)
