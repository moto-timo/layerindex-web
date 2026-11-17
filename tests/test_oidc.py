# layerindex-web - tests for the optional Authentik OIDC login
#
# Licensed under the MIT license, see COPYING.MIT for details
#
# SPDX-License-Identifier: MIT
#
# AI-generated, Claude Opus 5.5

# The backend in layerindex/oidc.py decides which local account an SSO login
# gets, and with which privileges. A wrong answer is an account takeover, so
# these tests pin down that behaviour without a running Authentik.

import pytest
from django.contrib.auth.models import Group, User
from django.test import RequestFactory, override_settings

from layerindex.oidc import LayerIndexOIDCBackend, provider_logout

# The settings mozilla-django-oidc needs to build a backend; docker/settings.py
# only sets them when OIDC_RP_CLIENT_ID is set
OIDC_SETTINGS = {
    'OIDC_RP_CLIENT_ID': 'layerindex',
    'OIDC_RP_CLIENT_SECRET': 'secret',
    'OIDC_OP_TOKEN_ENDPOINT': 'https://auth.example.com/application/o/token/',
    'OIDC_OP_USER_ENDPOINT': 'https://auth.example.com/application/o/userinfo/',
    'OIDC_OP_JWKS_ENDPOINT': 'https://auth.example.com/application/o/layerindex/jwks/',
    'OIDC_RP_SIGN_ALGO': 'RS256',
    'OIDC_RP_SCOPES': 'openid email profile',
    'OIDC_STAFF_GROUPS': [],
    'OIDC_SUPERUSER_GROUPS': [],
    'OIDC_MANAGED_GROUPS': [],
    'AUTHENTIK_URL': 'https://auth.example.com',
    'AUTHENTIK_APP_SLUG': 'layerindex',
    'LOGOUT_REDIRECT_URL': '/layerindex/',
}

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def oidc_settings():
    with override_settings(**OIDC_SETTINGS):
        yield


@pytest.fixture
def backend():
    return LayerIndexOIDCBackend()


def claims(**extra):
    base = {'email': 'alice@example.com', 'email_verified': True,
            'preferred_username': 'alice', 'name': 'Alice Liddell', 'groups': []}
    base.update(extra)
    return base


# verify_claims: the guard against taking over an account by its email

def test_verified_email_is_accepted(backend):
    assert backend.verify_claims(claims())


@pytest.mark.parametrize('verified', [False, None, 'true', 1])
def test_unverified_email_is_rejected(backend, verified):
    # Authentik >= 2025.10 sends email_verified: false by default
    assert not backend.verify_claims(claims(email_verified=verified))


def test_missing_email_verified_is_rejected(backend):
    c = claims()
    del c['email_verified']
    assert not backend.verify_claims(c)


@pytest.mark.parametrize('email', ['', None])
def test_missing_email_is_rejected(backend, email):
    assert not backend.verify_claims(claims(email=email))


def test_verification_can_be_turned_off(backend):
    with override_settings(OIDC_REQUIRE_VERIFIED_EMAIL=False):
        assert backend.verify_claims(claims(email_verified=False))


# filter_users_by_claims: which local account a login gets

def test_links_to_existing_account_by_email_ignoring_case(backend):
    user = User.objects.create_user('tim', email='Alice@Example.com')
    assert list(backend.filter_users_by_claims(claims())) == [user]


def test_does_not_link_by_username(backend):
    # Usernames are self-chosen, so an IdP username must not claim a local one
    User.objects.create_user('alice', email='someone-else@example.com')
    assert not backend.filter_users_by_claims(claims()).exists()


def test_no_email_links_to_nobody(backend):
    User.objects.create_user('blank', email='')
    assert not backend.filter_users_by_claims(claims(email='')).exists()


# get_username and create_user: new accounts

def test_username_from_preferred_username(backend):
    assert backend.get_username(claims()) == 'alice'


def test_username_falls_back_to_email_local_part(backend):
    assert backend.get_username(claims(preferred_username=None)) == 'alice'


def test_username_taken_gets_a_suffix(backend):
    User.objects.create_user('alice')
    User.objects.create_user('alice2')
    assert backend.get_username(claims()) == 'alice3'


def test_new_user_has_no_password_and_gets_names(backend):
    user = backend.create_user(claims())
    assert user.username == 'alice'
    assert user.email == 'alice@example.com'
    assert not user.has_usable_password()
    assert (user.first_name, user.last_name) == ('Alice', 'Liddell')


def test_update_keeps_names_already_set(backend):
    user = User.objects.create_user('tim', email='alice@example.com',
                                    first_name='Tim', last_name='O')
    backend.update_user(user, claims(given_name='Alice', family_name='L'))
    user.refresh_from_db()
    assert (user.first_name, user.last_name) == ('Tim', 'O')


# _sync_groups: privileges follow the IdP's groups

@override_settings(OIDC_STAFF_GROUPS=['li-staff'], OIDC_SUPERUSER_GROUPS=['li-admin'],
                   OIDC_MANAGED_GROUPS=['li-staff', 'li-admin'])
def test_groups_grant_and_revoke_privileges(backend):
    user = backend.create_user(claims(groups=['li-admin']))
    assert user.is_superuser and user.is_staff
    assert set(user.groups.values_list('name', flat=True)) == {'li-admin'}

    backend.update_user(user, claims(groups=['li-staff']))
    user.refresh_from_db()
    assert user.is_staff and not user.is_superuser
    assert set(user.groups.values_list('name', flat=True)) == {'li-staff'}

    backend.update_user(user, claims(groups=[]))
    user.refresh_from_db()
    assert not user.is_staff and not user.is_superuser
    assert not user.groups.exists()


def test_privileges_left_alone_without_group_settings(backend):
    # With no group mapping configured, privileges are managed in Django only
    user = User.objects.create_user('admin', email='alice@example.com',
                                    is_staff=True, is_superuser=True)
    other = Group.objects.create(name='other')
    user.groups.add(other)
    backend.update_user(user, claims(groups=[]))
    user.refresh_from_db()
    assert user.is_staff and user.is_superuser
    assert list(user.groups.all()) == [other]


# provider_logout: Authentik's end-session URL

def test_logout_url_passes_id_token_and_redirect():
    request = RequestFactory().get('/oidc/logout/')
    request.session = {'oidc_id_token': 'tok'}
    url = provider_logout(request)
    assert url.startswith('https://auth.example.com/application/o/layerindex/end-session/?')
    assert 'id_token_hint=tok' in url
    assert 'post_logout_redirect_uri=http%3A%2F%2Ftestserver%2Flayerindex%2F' in url


def test_logout_url_without_id_token():
    request = RequestFactory().get('/oidc/logout/')
    request.session = {}
    assert 'id_token_hint' not in provider_logout(request)
