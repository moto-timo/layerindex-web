# ---------------------------------------------------------------------------
# Production hardening + optional Authentik SSO for the containerised deploy.
#
# Append this block to docker/settings.py (which the Dockerfile copies over
# settings.py inside the image):
#
#     cat deploy/settings_append.py >> docker/settings.py
#
# Everything here is driven by environment variables and is inert unless those
# are set, so appending it does not change behaviour on its own.
#
# SPDX-License-Identifier: MIT
# ---------------------------------------------------------------------------

def _env_flag(name, default=False):
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ('1', 'true', 'yes', 'on')


def _env_list(name):
    return [x.strip() for x in os.getenv(name, '').split(',') if x.strip()]


# --- TLS-only cookies ------------------------------------------------------
# Caddy terminates TLS and redirects HTTP to HTTPS, so cookies should never be
# sent in the clear. Guarded on DEBUG so the local dev compose still works.
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    CSRF_COOKIE_SAMESITE = 'Lax'
    # Caddy issues the 80 -> 443 redirect; leaving this False avoids a second,
    # redundant redirect chain inside Django.
    SECURE_SSL_REDIRECT = False

# --- self-registration -----------------------------------------------------
# django_registration 5.2.1 RegistrationView.registration_allowed() reads this.
# CaptchaRegistrationView subclasses it, so the override applies to layerindex's
# custom registration view too. Set REGISTRATION_OPEN=0 once SSO is the only
# supported way in. Requires templates/django_registration/registration_closed.html
# (the package does not ship one).
REGISTRATION_OPEN = _env_flag('REGISTRATION_OPEN', True)

# --- Authentik OIDC SSO ----------------------------------------------------
# Entirely off unless OIDC_RP_CLIENT_ID is set in the environment.
OIDC_RP_CLIENT_ID = os.getenv('OIDC_RP_CLIENT_ID', '')
ENABLE_OIDC = bool(OIDC_RP_CLIENT_ID)

if ENABLE_OIDC:
    AUTHENTIK_URL = os.getenv('AUTHENTIK_URL', '').rstrip('/')
    AUTHENTIK_APP_SLUG = os.getenv('AUTHENTIK_APP_SLUG', 'layerindex')
    _AK_O = '%s/application/o' % AUTHENTIK_URL

    OIDC_RP_CLIENT_SECRET = os.getenv('OIDC_RP_CLIENT_SECRET', '')

    # In Authentik, authorize/token/userinfo are global endpoints; only jwks,
    # end-session and the discovery document are scoped to the application slug.
    # Sanity-check against:
    #   {AUTHENTIK_URL}/application/o/{slug}/.well-known/openid-configuration
    OIDC_OP_AUTHORIZATION_ENDPOINT = '%s/authorize/' % _AK_O
    OIDC_OP_TOKEN_ENDPOINT = '%s/token/' % _AK_O
    OIDC_OP_USER_ENDPOINT = '%s/userinfo/' % _AK_O
    OIDC_OP_JWKS_ENDPOINT = '%s/%s/jwks/' % (_AK_O, AUTHENTIK_APP_SLUG)

    # Requires a Signing Key on the Authentik provider. Without one Authentik
    # signs the ID token symmetrically with the client secret (HS256), which
    # would need OIDC_RP_SIGN_ALGO='HS256' and OIDC_RP_IDP_SIGN_KEY instead.
    OIDC_RP_SIGN_ALGO = os.getenv('OIDC_RP_SIGN_ALGO', 'RS256')
    OIDC_RP_SCOPES = os.getenv('OIDC_RP_SCOPES', 'openid email profile')
    OIDC_USE_PKCE = True
    OIDC_TOKEN_USE_BASIC_AUTH = True

    OIDC_CREATE_USER = _env_flag('OIDC_CREATE_USER', True)
    # Needed so provider_logout() can pass id_token_hint on the way out.
    OIDC_STORE_ID_TOKEN = True
    OIDC_OP_LOGOUT_URL_METHOD = 'layerindex.oidc.provider_logout'

    # Authentik group name -> Django privilege. Comma-separated.
    OIDC_STAFF_GROUPS = _env_list('OIDC_STAFF_GROUPS')
    OIDC_SUPERUSER_GROUPS = _env_list('OIDC_SUPERUSER_GROUPS')
    OIDC_MANAGED_GROUPS = _env_list('OIDC_MANAGED_GROUPS') or list(
        dict.fromkeys(OIDC_STAFF_GROUPS + OIDC_SUPERUSER_GROUPS))

    # Authentik >= 2025.10 emits email_verified=false by default. Set
    # OIDC_REQUIRE_VERIFIED_EMAIL=0 only if you understand the account-takeover
    # risk described in deploy/README.md.
    OIDC_REQUIRE_VERIFIED_EMAIL = _env_flag('OIDC_REQUIRE_VERIFIED_EMAIL', True)

    LOGOUT_REDIRECT_URL = '/layerindex/'

    INSTALLED_APPS = tuple(INSTALLED_APPS) + ('mozilla_django_oidc',)

    # Order matters. The OIDC backend goes FIRST: mozilla-django-oidc's
    # authenticate() returns None immediately unless ?code= and ?state= are
    # present, so ordinary password logins still fall through to Axes exactly as
    # before. Putting Axes first instead would let an IP-based lockout from
    # password brute force also block SSO logins, because the OIDC callback
    # calls authenticate() with no username and AxesBackend raises
    # PermissionDenied, which aborts the whole backend chain.
    AUTHENTICATION_BACKENDS = [
        'layerindex.oidc.LayerIndexOIDCBackend',
        'axes.backends.AxesBackend',
        'django.contrib.auth.backends.ModelBackend',
    ]

    # Belt and braces: never match a lockout record on IP alone, so a shared
    # NAT egress cannot lock everyone out of SSO.
    AXES_LOCKOUT_PARAMETERS = [['username', 'ip_address']]
