from django.contrib.postgres.fields import ArrayField, JSONField
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils.translation import ugettext_lazy as _

from timezone_field import TimeZoneField
from model_utils.models import TimeStampedModel

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
    is_active = models.BooleanField(default=True, verbose_name="Active")
    subaccount_id = models.SlugField(max_length=255, unique=True, null=True)
    silent_recipients = models.ManyToManyField(
        'SilentRecipient',
        blank=True,
        help_text='These are the non-team members that need to receive team updates via email such as clients. \
                  They can access the platform using their email and password.'
    )

    def __str__(self):
        return self.name

    def get_updates(self, for_date):
        """
        Returns a list of dictionaries that contains a `member` key with the
        full name of the team member and `update` key containing the `<DailyUpdate>`
        object based on `for_date` arg.

        If the member has multiple updates for the given date, it will return the first entry.

        If the member has no update for the given date, `update` key's value will be None.

        Arguments:
            `for_date`: `datetime.datetime` object with UTC as timezone

        Output example:
            [
                {
                    'member': 'John Doe',
                    'role': 'Developer'
                    'update': <DailyUpdate>,
                },
                {
                    'member': 'Jane Doe',
                    'role': 'Designer'
                    'update': <DailyUpdate>,
                },
            ]
        """
        members_and_updates = []

        for membership in self.memberships.filter(is_active=True):
            # NOTE: Needs improvement?
            update = (
                membership.updates.filter(for_date__year=for_date.year,
                                          for_date__month=for_date.month,
                                          for_date__day=for_date.day)
                                  .first()
            )
            members_and_updates.append({
                'member': membership.user.get_full_name() or membership.user.email,
                'update': update,
                'role': membership.role.name,
            })

        return members_and_updates

    def get_recipients(self, for_project_managers=False):
        """
        If `for_project_managers` is True, only return emails of members who are Project Managers
        """
        if for_project_managers:
            return [self.created_by.email]
        else:
            team_members = self.memberships.filter(is_active=True).values_list(
                'user__email', flat=True
            )
            silent_recipients = self.silent_recipients.values_list('user__email', flat=True)

            return list(
                set(list(team_members) + list(silent_recipients) + [self.created_by.email, ])
            )


class Role(models.Model):
    """
    User's role in a team.

    E.g: Project Manager, Developer, Designer, Tester
    """
    name = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.name


class Membership(models.Model):
    team = models.ForeignKey(Team, related_name='memberships')
    user = models.ForeignKey(User, related_name='memberships')
    role = models.ForeignKey(Role, on_delete=models.CASCADE, null=True)
    is_active = models.BooleanField(default=True, verbose_name='Active')

    class Meta:
        unique_together = (('team', 'user'),)

    def __str__(self):
        return '{} - {}'.format(self.team,
                                self.user.name)


class Update(models.Model):
    membership = models.ForeignKey(Membership, related_name='updates')
    for_date = models.DateField()
    done = models.TextField(
        blank=True
    )
    will_do = models.TextField(
        blank=True
    )
    blocker = models.TextField(
        blank=True
    )

    def __str__(self):
        return '{} - {}'.format(self.membership.user.get_full_name(),
                                self.for_date)

    # TODO: improve; use lambda + filter?
    def done_as_list(self):
        return [
            done for done in self.done.strip().split('\n')
            if done.strip()
        ]

    def will_do_as_list(self):
        return [
            will_do for will_do in self.will_do.strip().split('\n')
            if will_do.strip()
        ]

    def blocker_as_list(self):
        return [
            blocker for blocker in self.blocker.strip().split('\n')
            if blocker.strip()
        ]

    def is_editable(self):
        current_date = timezone.now().astimezone(
            pytz.timezone('Asia/Manila')
        )

        if current_date <= self.for_date:
            return True
        else:
            return False



class SilentRecipient(models.Model):
    user = models.OneToOneField(User)

    def __str__(self):
        return "{} - {}".format(self.user.get_full_name(), self.user.email)


class InboundWebhookRequest(TimeStampedModel):
    """
    POST requests from Mandrill's Inbound Email Webhooks are saved in this model.

    See: https://mandrill.zendesk.com/hc/en-us/articles/205583207-What-is-the-format-of-inbound-email-webhooks-
    """
    timestamp = models.DateTimeField()
    message = JSONField()
    daily_update = models.ForeignKey(
        'Update',
        blank=True,
        null=True,
        related_name='webhook_requests',
    )

    def __str__(self):
        email_data = json.loads(self.message)
        sender = email_data['from_email']
        return 'From {} @ {}'.format(
            sender,
            self.timestamp.strftime('%c'),
        )
