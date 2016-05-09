import datetime
import json

from django.conf import settings
from django.utils import timezone

import factory

from . import models

from digestus.users.tests.factories import UserFactory


class TeamFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Team

    name = factory.Sequence(lambda e: 'team_%d' % e)
    description = 'Awesome Description'
    email = factory.Sequence(lambda e: 'team_{num}@{domain}'.format(
        num=e,
        domain=settings.INBOUND_DOMAIN))
    digest_days_sent = [0, 1, 2, 3, 4]
    send_digest_at = datetime.time(9, 0)
    send_reminders_at = datetime.time(18, 0)
    created_by = factory.SubFactory(UserFactory)
    subaccount_id = factory.Sequence(lambda e: 'team_%d' % e)


class SilentRecipientFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.SilentRecipient

    user = factory.SubFactory(UserFactory)


class RoleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Role

    name = factory.Sequence(lambda e: 'Role #%d' % e)


class TeamMembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Membership

    team = factory.SubFactory(TeamFactory)
    user = factory.SubFactory(UserFactory)
    role = factory.SubFactory(RoleFactory)
    is_active = True


class UpdateFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Update

    membership = factory.SubFactory(TeamMembershipFactory)
    done = 'Tasks Done'
    will_do = 'Task to do today'
    blocker = 'Hindrance achieving the task'
    for_date = datetime.date.today() + datetime.timedelta(days=1)


class InboundWebhookRequestFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.InboundWebhookRequest

    timestamp = timezone.now()
    message = json.dumps({
        'text': '-do +will *block',
        'email': 'awesome@digestus.com',
        'from_email': 'sender@test.com'
    })
