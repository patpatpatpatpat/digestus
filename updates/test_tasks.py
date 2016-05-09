from datetime import datetime
from datetime import time

from django.core import mail
from django.test import TestCase

import mandrill
import pytz
from unittest import mock

from .factories import TeamFactory, TeamMembershipFactory, UpdateFactory, SilentRecipientFactory
from .tasks import (
    send_reminders,
    schedule_reminders,
    remind_team_member,
    send_digest,
    schedule_digest,
    wrong_email_format_reply,
)
from digestus.users.tests.factories import UserFactory


class ScheduleRemindersTest(TestCase):
    def setUp(self):
        self.developer = UserFactory()
        monday_to_friday = [0, 1, 2, 3, 4]
        self.digest_time = time(9, 0)
        self.reminder_time = time(18, 0)
        self.team = TeamFactory(digest_days_sent=monday_to_friday,
                                send_digest_at=self.digest_time,
                                send_reminders_at=self.reminder_time)
        TeamMembershipFactory(user=self.developer,
                              team=self.team)

    @mock.patch('updates.tasks.send_reminders.apply_async')
    @mock.patch('updates.tasks.timezone.now')
    def test_no_reminders(self, today, send_reminders_task):
        """
        Today is Saturday.

        Saturday is not included in `digest_days_sent` of Team.

        Therefore, no reminders for the team should be sent.
        """
        saturday = datetime(year=2015,
                            month=1,
                            day=3,
                            tzinfo=pytz.UTC)
        today.return_value = saturday

        schedule_reminders()

        self.assertFalse(send_reminders_task.called)

    @mock.patch('updates.tasks.send_reminders.apply_async')
    @mock.patch('updates.tasks.timezone.now')
    def test_send_reminders(self, today, send_reminders_task):
        """
        Today is Monday.

        Monday is included in `digest_days_sent` of Team.

        Therefore, reminders for the team should be sent.
        """
        monday = datetime(year=2015,
                          month=1,
                          day=5,
                          tzinfo=pytz.UTC)
        today.return_value = monday

        schedule_reminders()

        expected_function_args = ((self.team.id,),)
        expected_async_call_args = {
            'eta': monday.astimezone(pytz.timezone('Asia/Manila')).replace(
                hour=self.reminder_time.hour,
                minute=self.reminder_time.minute
            )
        }

        self.assertTrue(send_reminders_task.called)
        self.assertEqual(send_reminders_task.call_count, 1)
        self.assertEqual(send_reminders_task.call_args_list[0][0], expected_function_args)
        self.assertEqual(send_reminders_task.call_args_list[0][1], expected_async_call_args)

    @mock.patch('updates.tasks.send_reminders.apply_async')
    @mock.patch('updates.tasks.timezone.now')
    def test_disable_send_reminders_inactive_team(self, today, send_reminders_task):
        """
        Given that the team is inactive.

        Send reminders should not be called.

        Therefore, call count should be 0.
        """
        self.team.is_active = False
        self.team.save()

        schedule_reminders()

        self.assertFalse(send_reminders_task.called)
        self.assertEqual(send_reminders_task.call_count, 0)


class SendRemindersTest(TestCase):
    @mock.patch('updates.tasks.remind_team_member.delay')
    @mock.patch('updates.tasks.mandrill.Mandrill')
    def test_team_has_no_recipients(self, mandrill_client, remind_team_member):
        """
        Do not send reminder emails if the team has no members.
        """
        self.team_with_no_members = TeamFactory()

        send_reminders(self.team_with_no_members.id)

        self.assertFalse(remind_team_member.called)
        self.assertFalse(mandrill_client.called)

    @mock.patch('updates.tasks.remind_team_member.delay')
    @mock.patch('updates.tasks.mandrill.Mandrill')
    def test_reminder_sending_successful(self, mandrill_client, remind_team_member):
        """
        Reminder emails will be sent if:
            - Team has members
            - Team has a valid Mandrill subaccount
        """
        developer = UserFactory()
        valid_team = TeamFactory(created_by=developer, is_active=True)
        self.team_membership_1 = TeamMembershipFactory(team=valid_team,
                                                       user=developer)

        send_reminders(valid_team.pk)

        self.assertTrue(mandrill_client.called)
        self.assertEqual(remind_team_member.call_count, 1)

    @mock.patch('updates.tasks.logger.exception')
    @mock.patch('updates.tasks.remind_team_member.delay')
    @mock.patch('updates.tasks.mandrill.Mandrill')
    def test_invalid_mandrill_subaccount(self,
                                         mandrill_client,
                                         remind_team_member,
                                         logger):
        """
        Do not send reminder emails if the team has an invalid Mandrill subaccount.
        """
        developer = UserFactory()
        team_with_invalid_subaccount = TeamFactory(subaccount_id='invalid_subaccount')
        TeamMembershipFactory(user=developer,
                              team=team_with_invalid_subaccount)
        instance = mandrill_client.return_value
        instance.subaccounts.info.side_effect = mandrill.UnknownSubaccountError('Test Error')

        send_reminders(team_with_invalid_subaccount.id)

        self.assertTrue(logger.called)
        self.assertTrue(mandrill_client.called)
        self.assertFalse(remind_team_member.called)

    @mock.patch('updates.tasks.timezone.now')
    @mock.patch('updates.tasks.remind_team_member.delay')
    @mock.patch('updates.tasks.mandrill.Mandrill')
    def test_send_reminder_with_todos_or_blockers(self,
                                                  mandrill_client,
                                                  remind_team_member,
                                                  today):
        """
        Send reminder including the member's TODO and BLOCKERS from the latest update
        """
        monday_jan_5_2015_utc = datetime(2015, 1, 5)

        developer = UserFactory()
        valid_team = TeamFactory(created_by=developer, is_active=True)
        membership = TeamMembershipFactory(team=valid_team,
                                           user=developer)
        will_do = 'Finish Ticket #102\nOpen PR for Ticket #103\n'
        blockers = 'Slow internet connection\nPower Outage'
        update = UpdateFactory(
            membership=membership,
            done='Ticket #99',
            will_do=will_do,
            blocker=blockers,
            for_date=monday_jan_5_2015_utc,
        )
        today.return_value = monday_jan_5_2015_utc
        expected_args = (membership.id, update.will_do_as_list(), update.blocker_as_list())
        send_reminders(valid_team.id)

        self.assertTrue(remind_team_member.called)
        self.assertEqual(remind_team_member.call_count, 1)
        self.assertEqual(remind_team_member.call_args_list[0][0], expected_args)

    @mock.patch('updates.tasks.remind_team_member.delay')
    @mock.patch('updates.tasks.mandrill.Mandrill')
    def test_team_does_not_exist(self, mandrill_client, remind_team_member):
        """
        Given `team_id` does not exist!
        """
        invalid_team_id = 999

        send_reminders(invalid_team_id)

        self.assertFalse(mandrill_client.called)
        self.assertFalse(remind_team_member.called)

    @mock.patch('updates.tasks.send_reminders.apply_async')
    @mock.patch('updates.tasks.mandrill.Mandrill')
    def test_disable_send_reminders_inactive_teams(self, mandrill_client, send_reminders_task):
        """
        Given that the team is inactive.

        When the send_reminder task is being accessed

        It is asserted that call count is 0
        """
        developer = UserFactory()
        inactive_team = TeamFactory(created_by=developer, is_active=False)
        self.team_membership_1 = TeamMembershipFactory(team=inactive_team,
                                                       user=developer)

        send_reminders(inactive_team.pk)

        self.assertFalse(mandrill_client.called)
        self.assertFalse(send_reminders_task.called)
        self.assertEqual(send_reminders_task.call_count, 0)

    @mock.patch('updates.tasks.remind_team_member.delay')
    @mock.patch('updates.tasks.mandrill.Mandrill')
    def test_disable_send_reminders_team_members(self, mandrill_client, remind_team_member):
        """
        Given that the team is inactive and the members are inactive.

        When the send_reminder task is being accessed.

        It is asserted that the remind_team_member is not being called.
        """

        developer = UserFactory()
        inactive_team = TeamFactory(created_by=developer, is_active=False)
        self.team_membership_1 = TeamMembershipFactory(team=inactive_team,
                                                       user=developer,
                                                       is_active=False)

        send_reminders(inactive_team.pk)

        self.assertFalse(mandrill_client.called)
        self.assertEqual(remind_team_member.call_count, 0)


class ScheduleDigestTest(TestCase):
    def setUp(self):
        self.developer = UserFactory()
        monday_to_friday = [0, 1, 2, 3, 4]
        self.team = TeamFactory(digest_days_sent=monday_to_friday)
        TeamMembershipFactory(user=self.developer,
                              team=self.team)

    @mock.patch('updates.tasks.send_digest.apply_async')
    @mock.patch('updates.tasks.timezone.now')
    def test_send_digest(self, today, send_digest_task):
        """
        Today is Monday.

        Monday is included in `digest_days_sent` of Team.

        So, schedule digest sending!
        """
        monday = datetime(year=2015,
                          month=1,
                          day=5,
                          tzinfo=pytz.UTC)
        today.return_value = monday

        schedule_digest()
        expected_digest_eta_pht = (
            monday.astimezone(pytz.timezone('Asia/Manila')).replace(hour=self.team.send_digest_at.hour,
                                                                    minute=self.team.send_digest_at.minute)
        )
        expected_digest_eta_utc = expected_digest_eta_pht.astimezone(pytz.UTC)
        expected_function_args = ((self.team.pk, expected_digest_eta_utc),)
        expected_async_call_args = {'eta': expected_digest_eta_pht}

        self.assertTrue(send_digest_task.called)
        self.assertEqual(expected_function_args, send_digest_task.call_args_list[0][0])
        self.assertEqual(expected_async_call_args, send_digest_task.call_args_list[0][1])

    @mock.patch('updates.tasks.send_digest.apply_async')
    @mock.patch('updates.tasks.timezone.now')
    def test_no_digest(self, today, send_digest_task):
        """
        Today is Sunday.

        Sunday is not included in `digest_days_sent` of Team.

        So, do not schedule digest sending!
        """
        sunday = datetime(year=2015,
                          month=1,
                          day=4,
                          tzinfo=pytz.UTC)
        today.return_value = sunday

        schedule_digest()

        self.assertFalse(send_digest_task.called)

    @mock.patch('updates.tasks.send_digest.apply_async')
    @mock.patch('updates.tasks.timezone.now')
    def test_disable_schedule_digest_inactive_team(self, today, send_digest_task):
        """
        Given that the team is inactive.

        There should be no digest to be sent.

        Therefore, call for send digest should be false.
        """
        monday = datetime(year=2015,
                          month=1,
                          day=5,
                          tzinfo=pytz.UTC)
        today.return_value = monday
        self.team.is_active = False
        self.team.save()

        schedule_digest()

        self.assertFalse(send_digest_task.called)


class SendDigestTest(TestCase):
    def test_successful_digest_sending(self):
        """
        A `Team` has members, so send email digest to members.
        """
        for_date_jan_5_2015 = datetime(2015, 1, 5).replace(tzinfo=pytz.UTC)
        self.developer = UserFactory(email='dev_1@test.ph')
        self.silent_recipient = UserFactory(email='silent_1@test.ph')
        self.creator = UserFactory(email='team_creator1@test.ph')
        self.team = TeamFactory(digest_days_sent=[0, 1, 2, 3, 4],
                                email='success@test.com',
                                name='Success Team',
                                created_by=self.creator)
        self.team.silent_recipients.add(SilentRecipientFactory(user=self.silent_recipient))
        self.membership = TeamMembershipFactory(user=self.developer,
                                                team=self.team)

        send_digest(self.team.pk, for_date_jan_5_2015)

        expected_subject = 'Digest for Success Team for Mon, Jan 05 2015'
        expected_recipients = ['silent_1@test.ph', 'team_creator1@test.ph',
                               'dev_1@test.ph']
        expected_from_email = 'Digestus Digest <success@test.com>'
        msg = mail.outbox[0]
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(msg.subject, expected_subject)
        self.assertListEqual(sorted(msg.recipients()), sorted(expected_recipients))
        self.assertEqual(msg.from_email, expected_from_email)

    def test_team_has_no_members(self):
        """
        If `Team` has no members, no email should be sent.
        """
        for_date_jan_5_2015 = datetime(2015, 1, 5).replace(tzinfo=pytz.UTC)
        self.team = TeamFactory(digest_days_sent=[0, 1, 2, 3, 4])

        send_digest(self.team.pk, for_date_jan_5_2015)

        self.assertEqual(len(mail.outbox), 0)

    def test_digest_for_project_managers(self):
        """
        Only Project Managers should receive the digest.
        """
        for_date_jan_5_2015 = datetime(2015, 1, 5).replace(tzinfo=pytz.UTC)
        self.team_creator = UserFactory(email='tc@test.com')
        self.team = TeamFactory(digest_days_sent=[0, 1, 2, 3, 4], created_by=self.team_creator)
        self.team_membership = TeamMembershipFactory(team=self.team, user=self.team_creator)
        self.daily_update = UpdateFactory(membership=self.team_membership)

        send_digest(self.team.pk, for_date_jan_5_2015, for_project_managers=True)

        expected_recipients = ['tc@test.com']
        msg = mail.outbox[0]

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(msg.recipients(), expected_recipients)

    @mock.patch('updates.tasks.logger.exception')
    def test_digest_for_non_existent_team(self, exception_logger):
        """
        Log an error if team does not exist. Also log the team ID!
        """
        for_date_jan_5_2015 = datetime(2015, 1, 5).replace(tzinfo=pytz.UTC)
        invalid_team_id = 999

        send_digest(invalid_team_id, for_date_jan_5_2015)
        expected_log_message = 'Team with %s id does not exist.' % invalid_team_id

        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(exception_logger.called)
        self.assertTrue(expected_log_message, exception_logger.call_args_list[0][0])

    @mock.patch('updates.tasks.send_digest.retry')
    @mock.patch('updates.tasks.EmailMultiAlternatives')
    @mock.patch('updates.tasks.logger.exception')
    def test_retry_digest_sending_if_exception_occured(self, exception_logger, email, retry_task):
        """
        If an exception is raised when sending the digest,
        retry the task in 5 minutes.
        """
        for_date_jan_5_2015 = datetime(2015, 1, 5).replace(tzinfo=pytz.UTC)
        email_instance = email.return_value
        email_instance.send.side_effect = Exception('Dummy exception')
        self.team_creator = UserFactory(email='tc@test.com')
        self.team = TeamFactory(digest_days_sent=[0, 1, 2, 3, 4], created_by=self.team_creator)
        self.team_membership = TeamMembershipFactory(team=self.team, user=self.team_creator)

        send_digest(self.team.pk, for_date_jan_5_2015)

        self.assertTrue(exception_logger.called)
        self.assertTrue(retry_task.called)

    def test_disable_send_digest_to_inactive_teams(self):
        """
        Given that the team is inactive.

        It should not send any digest.

        Therefore, send_digest should not be called.
        """
        for_date_jan_5_2015 = datetime(2015, 1, 5).replace(tzinfo=pytz.UTC)
        self.developer = UserFactory(email='dev_1@test.com')
        self.silent_recipient = UserFactory(email='silent_1@test.com')
        self.team = TeamFactory(digest_days_sent=[0, 1, 2, 3, 4],
                                email='success@test.com',
                                name='Success Team',
                                is_active=False)
        self.team.silent_recipients.add(SilentRecipientFactory(user=self.silent_recipient))
        self.membership = TeamMembershipFactory(user=self.developer,
                                                team=self.team)

        send_digest(self.team.pk, for_date_jan_5_2015)

        self.assertEqual(len(mail.outbox), 0)


class RemindTeamMemberTest(TestCase):
    def setUp(self):
        self.team_member = UserFactory()
        self.team = TeamFactory()
        self.membership = TeamMembershipFactory(user=self.team_member,
                                                team=self.team)

    def test_reminder_with_no_todos_or_blockers(self):
        expected_subject = 'What did you get done today?'
        expected_from_email = 'Digestus Reminder <{email}>'.format(email=self.team.email)
        expected_recipients = [
            '{name} <{email}>'.format(name=self.team_member.get_full_name(),
                                      email=self.team_member.email)
        ]

        remind_team_member(self.membership.id)

        self.assertEqual(len(mail.outbox), 1)
        outgoing_email_message = mail.outbox[0]

        self.assertEqual(outgoing_email_message.subject, expected_subject)
        self.assertEqual(outgoing_email_message.from_email, expected_from_email)
        self.assertEqual(outgoing_email_message.recipients(), expected_recipients)

    def test_reminder_with_todos_or_blockers(self):
        """
        Blockers and will do items should be included in the email body.
        """
        will_do = ['Finish Ticket #102', 'Open PR for Ticket #103']
        blockers = ['Slow internet connection', 'Power outage']

        remind_team_member(self.membership.id, will_do, blockers)

        self.assertEqual(len(mail.outbox), 1)
        outgoing_email_message = mail.outbox[0]

        for todo in will_do:
            self.assertIn(todo, outgoing_email_message.body)

        for blocker in blockers:
            self.assertIn(blocker, outgoing_email_message.body)

    def test_team_membership_does_not_exist(self):
        """
        No TeamMembership for give `membership_id`
        """
        invalid_membership_id = 999

        remind_team_member(invalid_membership_id)

        self.assertEqual(len(mail.outbox), 0)

    @mock.patch('updates.tasks.remind_team_member.retry')
    @mock.patch('updates.tasks.logger.exception')
    @mock.patch('updates.tasks.EmailMultiAlternatives')
    def test_retry_reminder_sending_if_exception_occured(self, email, logger, retry_task):
        """
        If an exception is raised when sending the reminder,
        retry the task in 5 minutes.
        """
        instance = email.return_value
        instance.send.side_effect = Exception('Dummy exception')

        remind_team_member(self.membership.id)

        self.assertTrue(logger.called)
        self.assertTrue(retry_task.called)


class WrongEmailFormatTest(TestCase):
    def test_wrong_email_format_reply(self):
        """
        Given the email Format:
        ```
        ```

        Email for wrong format is sent.
        """
        self.developer = UserFactory(email="user@test.com")
        self.team = TeamFactory(name="Team",
                                email="team@digestus.com",
                                is_active=True)
        self.membership = TeamMembershipFactory(user=self.developer,
                                                team=self.team)

        wrong_email_format_reply(self.team.email, self.developer.email, 'email content')

        self.assertEqual(len(mail.outbox), 1)
