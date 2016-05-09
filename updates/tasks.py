import datetime
import logging

from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone

from celery import shared_task
import mandrill
import pytz

from .helpers import get_domain_name
from .models import Team, Membership

logger = logging.getLogger('put')


@shared_task
def schedule_reminders():
    """
    Schedule sending of reminders to each member in an active `Team`.
    A team is considered active if the length of its `days_sent` field is greater
    than 0 and the team has at least 1 active member.

    Sends email reminders the day before each day in `Team.days_sent` field.
    """
    has_days_sent_data = ~Q(digest_days_sent__len=0)
    active_teams = (
        Team.objects.filter(has_days_sent_data,
                            memberships__is_active__gt=0,
                            is_active=True)
                    .distinct()
    )
    for team in active_teams:
        ph_tz = pytz.timezone('Asia/Manila')
        today = timezone.now().astimezone(ph_tz)

        if today.weekday() in team.digest_days_sent:
            reminders_eta = today.replace(
                hour=team.send_reminders_at.hour,
                minute=team.send_reminders_at.minute,
            )
            send_reminders.apply_async(
                (team.id,),
                eta=reminders_eta,
            )


@shared_task
def remind_team_member(membership_id, previous_todos=None, previous_blockers=None):
    """
    Sends an individual reminder to a user.

    Includes TODOs and blockers if provided.
    """
    try:
        membership = Membership.objects.get(id=membership_id, is_active=True)
    except Membership.DoesNotExist:
        logger.error(
            "Active Membership with %s ID does not exist." % membership_id)
        return

    subject = 'What did you get done today?'
    from_email = 'Digestus Reminder <{email}>'.format(email=membership.team.email)
    recipient = [
        '{name} <{email}>'.format(name=membership.user.get_full_name(),
                                  email=membership.user.email)
    ]
    context = {
        'team_email': membership.team.email,
        'team_name': membership.team.name,
        'previous_todos': previous_todos,
        'previous_blockers': previous_blockers,
        'domain': get_domain_name(),
    }
    text_body = render_to_string('updates/emails/reminder.txt', context)

    email_msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=from_email,
        to=recipient,
    )
    email_msg.subaccount = membership.team.subaccount_id

    try:
        email_msg.send()
    except Exception as e:
        logger.exception('Failed to send team member reminder. Retrying in 5 minutes.')
        remind_team_member.retry(
            args=[membership_id, previous_todos, previous_blockers],
            exc=e,
            countdown=300,
            max_retries=5,
        )


@shared_task
def send_reminders(team_id):
    """
    Sends reminder emails to all members of the team if:
        1. The team has one or more active members
        2. The team has a valid Mandrill subaccount
    """
    try:
        team = Team.objects.get(id=team_id, is_active=True)
    except Team.DoesNotExist:
        logger.error(
            "Active team with %s ID does not exist." % team_id)
        return

    # Team should have members
    if not team.memberships.filter(is_active=True):
        logger.error(
            "Active team %s has no active members. Sending of reminders aborted" % team.name)
        return

    # Team should have a valid Mandrill subaccount
    mc = mandrill.Mandrill(settings.MANDRILL_API_KEY)

    try:
        mc.subaccounts.info(id=team.subaccount_id)
    except Exception:
        logger.exception(
            "Active team %s has an invalid subaccount. Sending of reminders aborted" % team.name)
        return

    today = timezone.now()
    for membership in team.memberships.filter(is_active=True):
        update = membership.updates.filter(
            for_date__year=today.year,
            for_date__month=today.month,
            for_date__day=today.day,
        ).first()

        if update and (update.will_do or update.blocker):
            remind_team_member.delay(
                membership.id,
                update.will_do_as_list(),
                update.blocker_as_list(),
            )
        else:
            remind_team_member.delay(membership.id)


@shared_task
def schedule_digest():
    """
    Schedule sending of digests to all active members and silent recipients in an active `Team`.
    """
    has_days_sent_data = ~Q(digest_days_sent__len=0)
    active_teams = (
        Team.objects.filter(has_days_sent_data,
                            is_active=True,
                            memberships__is_active__gt=0)
                    .distinct()
    )
    for team in active_teams:
        ph_tz = pytz.timezone('Asia/Manila')
        today = timezone.now().astimezone(ph_tz)

        if today.weekday() in team.digest_days_sent:
            digest_eta = today.replace(
                hour=team.send_digest_at.hour,
                minute=team.send_digest_at.minute,
            )
            send_digest.apply_async(
                (team.id, digest_eta.astimezone(pytz.UTC)),
                eta=digest_eta,
            )

            # TODO: test for project managers early updates
            # Send digest an hour before to Project Managers
            pm_digest_eta = digest_eta - datetime.timedelta(hours=1)
            send_digest.apply_async(
                (team.id, digest_eta.astimezone(pytz.UTC), True),
                eta=pm_digest_eta,
            )


@shared_task
def send_digest(team_id, for_date, for_project_managers=False):
    """
    Sends digest for the given date to all active members and silent
    recipients of the team.

    Arguments:
        `team`: `Team` object
        `for_date`: A `datetime.datetime` instance in UTC
        `for_project_managers`: Boolean; whether to send only to Project Manager members
    """

    # TODO: create decorator for this repeating pattern: try...except
    try:
        team = Team.objects.get(id=team_id, is_active=True)
    except Team.DoesNotExist:
        logger.exception(
            "Active team with %s ID does not exist." % team_id)
        return

    team_updates = team.get_updates(for_date)

    if team_updates:
        ph_tz = pytz.timezone('Asia/Manila')
        update_for_date = for_date.astimezone(ph_tz).strftime('%a, %b %d %Y')
        context = {
            'members_and_updates': team.get_updates(for_date),
            'team': team,
            'date': update_for_date,
            'domain': get_domain_name(),
        }
        text_body = render_to_string('updates/emails/digest.txt', context)
        html_body = render_to_string('updates/emails/digest.html', context)

        # Prepare email
        from_email = 'Digestus Digest <{email}>'.format(email=team.email)
        subject = 'Digest for {team} for {date}'.format(team=team.name,
                                                        date=update_for_date)
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=from_email,
            to=team.get_recipients(for_project_managers),
        )
        msg.auto_text = True
        msg.preserve_recipients = True
        msg.auto_text = False
        msg.auto_html = False
        msg.attach_alternative(html_body, 'text/html')
        msg.content_subtype = 'html'
        msg.subaccount = team.subaccount_id

        try:
            msg.send()
        except Exception as e:
            logger.exception(
                'Digest sending failed for team with ID: %s. Retrying in 5 minutes.' % team_id)
            send_digest.retry(
                args=[team_id, for_date, for_project_managers],
                exc=e,
                countdown=300,
                max_retries=5,
            )
    else:
        error_msg = 'Team %s has no active members. Sending of digest aborted.' % team.name
        logger.error(error_msg)


@shared_task
def wrong_email_format_reply(inbound_email, from_email, email_text):
    subject = "FORMAT ERROR!!"
    context = {
        'email_text': email_text
    }
    text_body = render_to_string('updates/emails/auto_reply.txt', context)
    auto_reply = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=inbound_email,
        to=[from_email, ]
    )
    auto_reply.send()
