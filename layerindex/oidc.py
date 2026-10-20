# layerindex-web - OpenID Connect authentication against Authentik
#
# Only loaded when OIDC_RP_CLIENT_ID is set; see deploy/settings_append.py.
#
# SPDX-License-Identifier: MIT

import logging
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.models import Group
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

logger = logging.getLogger(__name__)


class LayerIndexOIDCBackend(OIDCAuthenticationBackend):
    """Authentik-flavoured OIDC backend.

    Differences from the stock backend:
      * requires a verified email before linking to an existing account
      * derives a readable username from preferred_username instead of the
        default base64(sha1(email)) blob
      * maps Authentik groups onto Django staff/superuser/group membership
    """

    def verify_claims(self, claims):
        if not super().verify_claims(claims):
            return False
        if not claims.get('email'):
            return False
        if getattr(settings, 'OIDC_REQUIRE_VERIFIED_EMAIL', True):
            if claims.get('email_verified') is not True:
                logger.warning(
                    'Rejecting OIDC login for %s: email_verified is not true. '
                    'Authentik >= 2025.10 emits false by default; add a scope '
                    'mapping that sets it honestly.', claims.get('email'))
                return False
        return True

    def filter_users_by_claims(self, claims):
        """Link to an existing local account by verified email address.

        Deliberately case-insensitive and deliberately *not* username-based:
        layerindex usernames are self-chosen and not namespaced by the IdP.
        """
        email = (claims.get('email') or '').strip()
        if not email:
            return self.UserModel.objects.none()
        return self.UserModel.objects.filter(email__iexact=email)

    def get_username(self, claims):
        candidate = (claims.get('preferred_username')
                     or (claims.get('email') or '').split('@')[0]
                     or 'user')
        candidate = candidate[:150]
        username, suffix = candidate, 1
        while self.UserModel.objects.filter(username=username).exists():
            suffix += 1
            username = '%s%d' % (candidate[:145], suffix)
        return username

    def create_user(self, claims):
        user = super().create_user(claims)
        # SSO accounts have no local password. This also means the security
        # question password-reset flow correctly never applies to them.
        user.set_unusable_password()
        return self.update_user(user, claims)

    def update_user(self, user, claims):
        if claims.get('email'):
            user.email = claims['email']
        if not (user.first_name or user.last_name):
            given = claims.get('given_name')
            family = claims.get('family_name')
            if not (given or family):
                given, _, family = (claims.get('name') or '').partition(' ')
            user.first_name = (given or '')[:150]
            user.last_name = (family or '')[:150]
        self._sync_groups(user, claims.get('groups') or [])
        user.save()
        return user

    def _sync_groups(self, user, idp_groups):
        idp = set(idp_groups)
        staff = set(getattr(settings, 'OIDC_STAFF_GROUPS', []))
        superuser = set(getattr(settings, 'OIDC_SUPERUSER_GROUPS', []))

        if superuser:
            user.is_superuser = bool(idp & superuser)
        if staff or superuser:
            user.is_staff = bool(idp & staff) or user.is_superuser

        for name in getattr(settings, 'OIDC_MANAGED_GROUPS', []):
            group, _ = Group.objects.get_or_create(name=name)
            if name in idp:
                user.groups.add(group)
            else:
                user.groups.remove(group)


def provider_logout(request):
    """Return Authentik's RP-initiated logout URL.

    mozilla-django-oidc calls this *before* django.contrib.auth.logout(), so
    the session still holds oidc_id_token (OIDC_STORE_ID_TOKEN must be True).

    Requires Authentik >= 2026.5: post_logout_redirect_uri was ignored by the
    end-session endpoint before that (goauthentik/authentik#19201, fixed by
    PR #20011), and the URI must be registered on the provider as a
    post-logout redirect URI.
    """
    params = {
        'post_logout_redirect_uri': request.build_absolute_uri(
            getattr(settings, 'LOGOUT_REDIRECT_URL', '/')),
    }
    id_token = request.session.get('oidc_id_token')
    if id_token:
        params['id_token_hint'] = id_token
    return '%s/application/o/%s/end-session/?%s' % (
        settings.AUTHENTIK_URL, settings.AUTHENTIK_APP_SLUG, urlencode(params))
