# layerindex-web - tests for changing the email address on the profile page
#
# Licensed under the MIT license, see COPYING.MIT for details
#
# SPDX-License-Identifier: MIT

import re
from urllib.parse import unquote

import pytest
from captcha.models import CaptchaStore
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.core import mail
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from layerindex.models import (Branch, LayerBranch, LayerItem, LayerMaintainer, SecurityQuestion,
                               SecurityQuestionAnswer, UserProfile)


@pytest.mark.django_db
class TestProfileEmailChange(TestCase):
    """Changing the email address must not take effect without proving
    ownership of the new address, since layer edit rights are granted by
    matching the user's email against (public) maintainer emails."""

    def setUp(self):
        self.user = User.objects.create_user('someone', 'old@example.com', 'pw')
        profile = UserProfile.objects.create(user=self.user)
        self.questions = [SecurityQuestion.objects.create(question='Question %d' % i) for i in range(3)]
        for question in self.questions:
            SecurityQuestionAnswer.objects.create(user=profile, security_question=question, answer='x')
        self.client.force_login(self.user)

    def _post_profile(self, email, password='pw', **extra):
        hashkey = CaptchaStore.generate_key()
        data = {**extra,
            'current_password': password,
            'username': 'someone',
            'first_name': '',
            'last_name': '',
            'email': email,
            'captcha_0': hashkey,
            'captcha_1': CaptchaStore.objects.get(hashkey=hashkey).response,
            'answer_1': '*****',
            'answer_2': '*****',
            'answer_3': '*****',
        }
        for i, question in enumerate(self.questions, 1):
            data['security_question_%d' % i] = question.pk
        return self.client.post(reverse('profile'), data)

    def test_email_change_requires_reactivation(self):
        response = self._post_profile('maintainer@example.com')
        self.assertRedirects(response, reverse('reregister'), fetch_redirect_response=False)

        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        # Logged out, and an inactive account cannot log back in
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertIsNone(authenticate(RequestFactory().post('/'), username='someone', password='pw'))
        # The activation link only goes to the new address, and the old
        # address is told about the change
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ['maintainer@example.com', 'old@example.com'])
        notice = [m for m in mail.outbox if m.to == ['old@example.com']][0]
        self.assertIn('was changed to maintainer@example.com', notice.body)
        self.assertNotIn('activation_key', notice.body)

    def test_email_change_needs_current_password(self):
        for password in ('', 'wrong'):
            response = self._post_profile('maintainer@example.com', password=password)
            self.assertEqual(response.status_code, 200)
            self.assertIn('current_password', response.context['form'].errors)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'old@example.com')
        self.assertTrue(self.user.is_active)
        self.assertEqual(len(mail.outbox), 0)

    def test_unchanged_email_keeps_account_active(self):
        response = self._post_profile('old@example.com')
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertEqual(len(mail.outbox), 0)

    def test_profile_requires_login(self):
        self.client.logout()
        for method in ('get', 'post'):
            response = getattr(self.client, method)(reverse('profile'))
            self.assertEqual(response.status_code, 302, method)
            self.assertIn(reverse('login'), response['Location'])
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'old@example.com')

    def test_maintainer_records_move_only_after_admin_approval(self):
        # [YOCTO #11195] a maintainer who changes their address keeps access
        # to their layers, but only once the new address is confirmed and a
        # site admin has approved it
        master, _ = Branch.objects.get_or_create(name='master', defaults={'bitbake_branch': 'master'})
        kirkstone = Branch.objects.create(name='kirkstone', bitbake_branch='2.0')
        layer = LayerItem.objects.create(name='meta-mine', status='P', layer_type='A', summary='x',
                                         description='x', vcs_url='git://example.com/meta-mine.git')
        mine = [LayerMaintainer.objects.create(layerbranch=LayerBranch.objects.create(layer=layer, branch=b),
                                               name='Someone', email=email)
                for b, email in ((master, 'old@example.com'), (kirkstone, 'Old@Example.com'))]
        other = LayerMaintainer.objects.create(layerbranch=mine[0].layerbranch, name='Other',
                                               email='other@example.com')
        admin = User.objects.create_superuser('admin', 'admin@example.com', 'pw')
        profile_pk = UserProfile.objects.get(user=self.user).pk

        def emails():
            return sorted(LayerMaintainer.objects.filter(pk__in=[m.pk for m in mine]).values_list('email', flat=True))

        def approve():
            client = Client()
            client.force_login(admin)
            return client.post(reverse('admin:layerindex_userprofile_changelist'),
                               {'action': 'approve_maintainer_email_change', '_selected_action': [profile_pk]},
                               follow=True)

        self._post_profile('new@example.com')
        # Approving before the new address is confirmed does nothing
        approve()
        self.assertEqual(emails(), ['Old@Example.com', 'old@example.com'])

        activation = [m for m in mail.outbox if m.to == ['new@example.com']][0]
        key = unquote(re.search(r'activation_key=(\S+)', activation.body).group(1))
        mail.outbox.clear()
        with self.settings(ADMINS=[('Admin', 'admin@example.com')]):
            response = self.client.post(reverse('django_registration_activate'), {'activation_key': key})
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        # Confirming the address alone moves nothing, but asks the admins
        self.assertEqual(emails(), ['Old@Example.com', 'old@example.com'])
        self.assertFalse(layer.user_can_edit(self.user))
        self.assertEqual([m.to for m in mail.outbox], [['admin@example.com']])
        self.assertIn('meta-mine (kirkstone)', mail.outbox[0].body)
        self.assertIn('once a site administrator approves', [str(m) for m in get_messages(response.wsgi_request)][0])

        mail.outbox.clear()
        approve()
        self.assertEqual(emails(), ['new@example.com', 'new@example.com'])
        other.refresh_from_db()
        self.assertEqual(other.email, 'other@example.com')
        self.assertTrue(layer.user_can_edit(self.user))
        self.assertEqual([m.to for m in mail.outbox], [['new@example.com']])
        self.assertEqual(UserProfile.objects.get(user=self.user).previous_email, '')

    def test_opt_in_to_parse_error_mail(self):
        # [YOCTO #11196]
        self._post_profile('old@example.com', notify_parse_errors='on')
        self.assertTrue(UserProfile.objects.get(user=self.user).notify_parse_errors)
        self._post_profile('old@example.com')
        self.assertFalse(UserProfile.objects.get(user=self.user).notify_parse_errors)
