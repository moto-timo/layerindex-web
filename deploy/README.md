# layerindex-web on Hetzner: Caddy TLS, then Authentik SSO

Investigation + working configuration for two phases:

1. **Phase 1 — Caddy.** Run the stack on a single Hetzner Cloud VM with Caddy as
   the reverse proxy, terminating TLS with automatically-issued Let's Encrypt
   certificates. Replaces `layersweb` (nginx) and the commented-out
   `layerscertbot` service.
2. **Phase 2 — Authentik SSO.** Add OpenID Connect login against an existing,
   separately-hosted Authentik instance, without tearing out the current
   local-account machinery.

Researched August 2026, Caddy pin re-verified October 2026. Versions pinned here: Caddy **2.11.7**,
mozilla-django-oidc **5.0.2**, Authentik **≥ 2026.5** required for logout
redirect, Django **5.2**.

## What's in this directory

```
deploy/
├── README.md                                  ← this file
└── hetzner/
    ├── docker-compose.yml                     production stack (Caddy, no nginx)
    ├── Caddyfile                              validated against caddy 2.11.7
    ├── Dockerfile.caddy                       optional: xcaddy + rate limiting
    ├── env.example                            copy to repo-root .env
    ├── bootstrap-host.sh                      fresh-VM prep
    └── backup-db.sh                           mariadb-dump + prune
```

The SSO code lives in the app: `layerindex/oidc.py` (the backend), the `oidc/`
routes in `urls.py`, the SSO block at the end of `docker/settings.py`, and the
`registration/login.html` and `django_registration/registration_closed.html`
templates.

---

# Phase 1 — Caddy on Hetzner

## Why Caddy is a clean fit here

The nginx setup this replaces is not just a proxy; `dockersetup.py` rewrites
`docker/nginx-ssl.conf` in place (hostname, ports, cert paths) into
`nginx-ssl-edited.conf`, drives certbot through a webroot dance in
`/var/www/certbot`, and juggles a self-signed bootstrap cert. That is ~200 lines
of Python whose entire job is to work around nginx not being able to get its own
certificates. Caddy does that natively, so the whole apparatus goes away:
`docker/certs/`, `certbotwww`, the `nginx -s reload` sleep loop in the compose
`command:`, and the `layerscertbot` service.

## Architecture

```
                 :80 :443 :443/udp
Internet ──────────────► layerscaddy ──── /static/*  → layersstatic volume (/srv)
                          (TLS, ACME)  └── everything → layersapp:5000 (gunicorn)

              layersapp ──┬── layersdb (mariadb, named volume)
              layerscelery┘── layersrabbit
```

Only Caddy publishes ports. The database, RabbitMQ and gunicorn stay on the
compose-internal network with no host binding.

## The five things that actually matter

**1. `/data` must be a persistent named volume.** It holds the ACME account key
and every issued certificate. If it is lost on each `docker compose down`, Caddy
re-registers and re-issues from scratch every time, and Let's Encrypt's
*duplicate certificate* limit is **5 per 7 days** for an identical name set.
Five recreates in a week locks you out of issuance for up to a week. This is the
single highest-consequence detail in the whole deploy.

**2. Static file mapping.** `dockersetup.py` runs collectstatic with the
`layersstatic` volume mounted at `/usr/share/nginx/html`, and
`docker/settings.py` hardcodes `STATIC_ROOT = '/usr/share/nginx/html/static/'`.
So files land at `<volume>/static/…`. Mount that volume at `/srv` in Caddy and
use `root * /srv` + `file_server` with **no** prefix stripping — `/static/x.css`
→ `/srv/static/x.css`. Using `handle_path /static/*` (which strips the prefix)
is the classic way to get a 404 wall here.

**3. `X-Forwarded-*` is already correct.** Caddy's `reverse_proxy` sets
`X-Forwarded-For`, `X-Forwarded-Proto` and `X-Forwarded-Host` by default and
*ignores* client-supplied values. `docker/settings.py` already has
`SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')` and
`USE_X_FORWARDED_HOST = True`, so there is nothing to add — and no `header_up`
lines to get wrong. Do **not** set `trusted_proxies` in the global block: Caddy
is the edge, and trusting proxies there would let clients spoof their own IP.

**4. `HOSTNAME` is a trap.** `docker/settings.py` derives `ALLOWED_HOSTS`,
`CSRF_TRUSTED_ORIGINS`, `DEFAULT_FROM_EMAIL` and `SUBMIT_EMAIL_FROM` from
`os.getenv('HOSTNAME')`. Docker sets `HOSTNAME` in the container automatically —
to the container ID, or to whatever `hostname:` says. The upstream compose file
sets `hostname: localhost`, which silently gives you
`ALLOWED_HOSTS = ['localhost']` and a `DisallowedHost` 400 on every real
request. The compose file here sets `HOSTNAME` explicitly as an environment
variable, which wins.

**5. HTTP→HTTPS redirection and the ACME challenge handler are automatic.**
Do not write an `http://…` site block; adding one *disables* the built-in
redirect and the HTTP-01 handler with it.

## Deployment runbook

### 0. Provision

`CX43` (8 vCPU / 16 GB / 160 GB NVMe, €15.99/mo) is the sweet spot. Hetzner's
15 June 2026 repricing raised CPX/CCX by 2.2–2.8× while CX/CAX rose only ~1.3×,
so the old "CPX for compute" heuristic now costs about 4× more for identical
specs (CPX42 is €69.49 for the same 8/16/320). Keep `LAYER_FETCH_DIR` on the
local NVMe rather than a Hetzner Volume — cloning ~400 git repos and parsing
them with bitbake is metadata- and IOPS-heavy, and Volumes cap at 5,000 IOPS /
200 MB/s. **Hetzner backups and snapshots do not include attached Volumes**,
which is a second reason to avoid them here.

Budget 60–120 GB for the layer clones alone (622 layers, ~350–450 unique repos,
30 branches on the public index). 160 GB is the floor; go CX53 (32 GB / 320 GB,
€29.49) if you index many branches. Enable automatic backups (+20% of server
price) and expect to restore the DB from `backup-db.sh` dumps — the git cache is
fully reconstructible and does not need backing up.

```sh
ssh root@<ip> sh /root/bootstrap-host.sh      # deploy/hetzner/bootstrap-host.sh
```

### 1. Firewall

Use the **Hetzner Cloud Firewall**, not ufw. Docker's iptables rules bypass
ufw/firewalld for published ports, so a host firewall gives false confidence;
the Cloud Firewall filters in Hetzner's network before traffic reaches the VM.

Inbound: `TCP 22` (your IPs only), `TCP 80`, `TCP 443`, `UDP 443` — each rule
with **both** `0.0.0.0/0` and `::/0` sources. Port 80 is not optional: Caddy
picks randomly between the HTTP-01 and TLS-ALPN-01 challenges, so opening only
443 produces intermittent, hard-to-diagnose issuance failures.

### 2. DNS

Point the A record at the VM **before** starting Caddy. If a name does not
resolve to the box, ACME fails, and Caddy backs off exponentially up to 1 day
between attempts for up to 30 days.

On IPv6: Hetzner gives every VM a free /64, but the guest sometimes needs manual
configuration, Cloud Firewall rules written only for `0.0.0.0/0` drop v6, and
Docker may not publish on `::` depending on `ip6tables` settings. Let's Encrypt
*prefers* AAAA when it exists, so a broken v6 path breaks issuance even though
v4 works. Publish AAAA only after `curl -6 http://<host>/` succeeds from a host
that has working IPv6. A-only is perfectly fine.

The AAAA record must be the VM's address inside the /64, normally `<prefix>::1`
(check with `ip -6 addr show scope global`). The bare `<prefix>::` shown in the
Console is the subnet itself and nothing answers there.

Set rDNS in the Console (Server → Networking). For IPv6 enter only the interface
identifier — the /64 prefix is already stored.

### 3. Email — read this before you wonder why registration is broken

**Hetzner Cloud blocks outbound TCP 25 and 465 by default.** Port 587 is open.
Unblocking requires a limit request at `https://console.hetzner.com/limits`,
only after your first paid invoice, and is granted case by case. Blocking is
per-account, not per-server.

layerindex sends activation mail, password-reset mail, layer-submission mail and
publish notifications, so this is load-bearing. Point `EMAIL_HOST`/`EMAIL_PORT`
at a relay on **587 with STARTTLS** (SES, Postmark, Mailgun, or your own MX).
Do this even if you get 25 unblocked — deliverability from a fresh Hetzner IP is
poor regardless.

### 4. Configure and start

```sh
sudo mkdir -p /srv/layerindex-web && sudo chown "$USER": /srv/layerindex-web
git clone <repo> /srv/layerindex-web && cd /srv/layerindex-web
# The Dockerfile does `COPY .`, so keep the secrets out of the image.
echo .env >> .dockerignore
cp deploy/hetzner/env.example .env && chmod 600 .env
python3 -c 'import secrets; print(secrets.token_urlsafe(64))'   # SECRET_KEY
$EDITOR .env
```

Compose reads `.env` from the directory of the compose file, not the current
directory, so every command needs `--env-file .env`. An alias saves typing:

```sh
alias dc='docker compose -f deploy/hetzner/docker-compose.yml --env-file .env'
dc config -q

# Test against Let's Encrypt staging first (expect a browser cert warning):
#   ACME_CA=https://acme-staging-v02.api.letsencrypt.org/directory
dc up -d --build

# Docker creates the static and task-log volumes owned by root, but the app
# runs as `layers`. Fix once; the ownership is stored in the volumes.
dc exec -u root layersapp chown -R layers /usr/share/nginx/html /opt/layerindex-task-logs

dc exec layersapp /opt/layerindex/manage.py migrate
dc exec layersapp /opt/layerindex/manage.py collectstatic --noinput
dc exec layersapp /opt/layerindex/manage.py createsuperuser
```

Switching from staging to production: comment out `ACME_CA`, then **delete the
staging artifacts** or Caddy will keep serving the untrusted cert. Use `up -d`,
not `restart`: `restart` does not pick up changes to `.env`.

```sh
dc exec layerscaddy \
  rm -rf /data/caddy/certificates/acme-staging-v02.api.letsencrypt.org-directory
dc up -d layerscaddy
```

### 5. Cookie hardening

`docker/settings.py` sets `SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE` when
`DEBUG` is off, since Caddy only serves the site over HTTPS. SSO stays off until
you set `OIDC_RP_CLIENT_ID`.

## Bugs in the upstream compose file, fixed here

These are worth knowing about regardless of Caddy:

| Upstream | Problem | Fix in `deploy/hetzner/docker-compose.yml` |
|---|---|---|
| `layersdb` has no volume | MariaDB data lives in an anonymous volume that `docker compose down` orphans | explicit `layersdbdata:/var/lib/mysql` |
| `layerscelery` uses `DATABASE_USER=layers` | Only `MYSQL_ROOT_PASSWORD` is set, so no `layers` user is ever created — celery cannot connect | `MARIADB_USER`/`MARIADB_PASSWORD` create it; both services use it |
| `layersapp` uses `DATABASE_USER=root` | App runs as DB root | app user for both |
| `MYSQL_ROOT_PASSWORD=testingpw` inline | Credentials in the tracked file | everything from `.env`, required via `${VAR:?}` |
| `hostname: localhost` | Becomes `ALLOWED_HOSTS` (see above) | explicit `HOSTNAME` env |
| no healthchecks | Celery/app race the DB on cold start | `service_healthy` gating |
| no `DJANGO_SETTINGS_MODULE` | The celery worker imports `layerindex.tasks` directly and exits with `ImproperlyConfigured` | set to `settings` for all app containers |

## What you lose, and what to do about it

The nginx config had `limit_req zone=login_ip rate=30r/m` on `/accounts/login`.
**Caddy 2.11.7 has no built-in rate limiter.** `mholt/caddy-ratelimit` exists and
is written by Caddy's author, but it is explicitly not an official Caddy
repository, is pre-1.0, and requires an `xcaddy` custom build.

`django-axes` is already installed and configured (`AXES_FAILURE_LIMIT = 4`,
`AXES_COOLOFF_TIME = 1`), which covers login brute force at the application
layer more precisely than an IP-bucket ever did. The recommendation is to skip
the custom Caddy build. `deploy/hetzner/Dockerfile.caddy` and a commented
`rate_limit` block in the Caddyfile are there if you disagree. The module
compiles against 2.11.7 and the uncommented block validates, but re-check after
any Caddy bump.

---

# Phase 2 — Authentik SSO

## The constraint that decides the design

layerindex's auth is not stock Django. It has:

- `django-registration` 5.2.1 with the activation-by-email backend
- `CaptchaRegistrationView` writing three hashed **security question answers**
  into a `UserProfile` at registration time
- `PasswordResetSecurityQuestions`, a custom password-reset confirm view that
  requires those answers and **deactivates the account + emails admins** after
  repeated wrong answers
- `django-simple-captcha` on registration and password reset
- `django-axes` with `AxesBackend` first in `AUTHENTICATION_BACKENDS`
- a public, anonymous, read-only DRF API

Any option that replaces `accounts/` wholesale has to reimplement all of that.

## Options considered

| | A. mozilla-django-oidc | B. django-allauth | C. Caddy `forward_auth` → Authentik proxy provider |
|---|---|---|---|
| Change footprint | ~30 lines of settings, 1 URL include, one new module | new apps, migrations, template overrides, URL de-confliction | small in Django, large in ops |
| Coexists with django-registration | yes, cleanly | no — allauth *is* a registration framework; running both is redundant | yes, but SSO bypasses it |
| `accounts/` URL collision | none (mounts at `oidc/`) | yes — allauth registers `login/`, `logout/`, `signup/`, `password/reset/`; first `include()` silently wins | n/a |
| DB migrations added | none | yes | none |
| Public anonymous API survives | yes | yes | **no** — the proxy gates the whole site |
| Django admin break-glass | yes (`ModelBackend` stays last) | yes | only if `/admin/` is excluded |
| Failure mode | login doesn't work | login doesn't work | **auth bypass**: any request reaching Django without traversing Caddy can set `X-authentik-username: admin` |

**Recommendation: A, mozilla-django-oidc 5.0.2**, added as an *additional*
backend rather than a replacement. It is additive, migration-free, reversible by
unsetting one environment variable, and leaves the local login path intact for
admins and for the transition period.

Option C is tempting because Caddy is already there, but it is the wrong shape
for this app: layerindex is a public browse-and-API site where most traffic must
stay anonymous, and header-trust auth has a bad track record (Authentik itself
shipped GHSA-7jxf-mmg9-9hg7, an auth bypass via `X-Forwarded-For`; Traefik has
two ForwardAuth spoofing advisories). Option D, SAML via djangosaml2, buys
nothing against an OIDC-capable IdP beyond XML signature handling.

## The two hazards worth spelling out

### django-axes aborts the OIDC callback

`AxesBackend.authenticate()` raises `AxesBackendPermissionDenied` when the
request is locked out, and Django's `authenticate()` aborts the **entire backend
chain** on `PermissionDenied`. mozilla-django-oidc's callback calls
`auth.authenticate(request=…, nonce=…, code_verifier=…)` through that same
chain, with **no username**. With axes' default lockout parameters that falls
back to IP matching — so an IP locked out by password brute force also cannot
complete an SSO login. Behind a shared NAT or a CI runner, that is a support
ticket.

The fix used here is ordering, and it is safe because of a specific property of
the library: `OIDCAuthenticationBackend.authenticate()` returns `None`
immediately unless both `?code=` and `?state=` are present in the request
(verified in 5.0.2 source). So putting it **first** costs nothing for password
logins — they fall straight through to axes exactly as before — while SSO
logins never reach axes at all:

```python
AUTHENTICATION_BACKENDS = [
    'layerindex.oidc.LayerIndexOIDCBackend',
    'axes.backends.AxesBackend',
    'django.contrib.auth.backends.ModelBackend',
]
AXES_LOCKOUT_PARAMETERS = [['username', 'ip_address']]   # belt and braces
```

### `email_verified` defaults to false in Authentik

Account linking is by **verified email, case-insensitive**. Username matching
would be worse — layerindex usernames are self-chosen and not namespaced by the
IdP. But since **Authentik 2025.10 the built-in `email` scope no longer
hardcodes `email_verified: true`; it defaults to `false`.** So the first thing
that happens when you enable this is that every login is rejected, and the
tempting fix is to delete the check.

Do not. If the IdP does not verify email ownership, anyone who can self-register
in Authentik as `tim.orling@konsulko.com` takes over that layerindex account —
including its staff/superuser bits. Add a scope mapping in Authentik that emits
`email_verified` honestly. `OIDC_REQUIRE_VERIFIED_EMAIL=0` exists as an escape
hatch for a closed IdP with no self-registration; it is not a fix.

Second, smaller hazard: `filter_users_by_claims` returning more than one user
makes login fail. Audit for duplicate or blank emails before rollout:

```sql
SELECT LOWER(email), COUNT(*) c FROM auth_user
WHERE email <> '' GROUP BY 1 HAVING c > 1;
```

If you want to be rigorous, add a small `OIDCLink(user, sub)` table keyed on the
immutable `sub` claim so a later email change in Authentik doesn't strand an
account. Not included here — it is a migration, and the email path is adequate
for a first cut.

## Authentik-side setup

Endpoints, for slug `layerindex` on `https://sso.example.com` — note that
`authorize`/`token`/`userinfo` are **global**, and only jwks, end-session and
discovery are slug-scoped, which is easy to get backwards:

| | |
|---|---|
| Discovery | `/application/o/layerindex/.well-known/openid-configuration` |
| Authorize | `/application/o/authorize/` |
| Token | `/application/o/token/` |
| UserInfo | `/application/o/userinfo/` |
| JWKS | `/application/o/layerindex/jwks/` |
| End session | `/application/o/layerindex/end-session/` |

Steps:

1. **Applications → Create with Provider**; name `Layer Index`, slug
   `layerindex`.
2. Provider type **OAuth2/OpenID**, client type **Confidential**.
3. **Redirect URI**: `https://layers.example.com/oidc/callback/` — a literal
   URL, strict match. Leaving it empty makes Authentik learn the first URL used,
   which you do not want in production.
4. **Post-logout redirect URI**: `https://layers.example.com/layerindex/`.
5. **Signing Key**: select a certificate. Without one Authentik signs the ID
   token symmetrically with the client secret (HS256), which would require
   `OIDC_RP_SIGN_ALGO='HS256'` plus `OIDC_RP_IDP_SIGN_KEY` instead of JWKS.
6. Scopes `openid email profile`. The default `profile` mapping already emits a
   `groups` claim, so no custom mapping is needed for group sync.
7. Add a scope mapping that sets `email_verified` truthfully (see above).
8. Create groups `layerindex-staff` and `layerindex-admins`; bind as needed.
9. Verify the discovery document loads.

**Authentik ≥ 2026.5 is required** for logout to redirect back. Before that the
end-session endpoint ignored `post_logout_redirect_uri`, didn't kill the
session, and didn't run the invalidation flow (goauthentik/authentik#19201,
fixed by PR #20011, merged 2026-04-07). Also note that `end_session` ends only
*that application's* session; the Authentik session itself survives unless you
configure full single logout (front-channel iframe or back-channel), and
mozilla-django-oidc ships no back-channel logout receiver — you would write that
endpoint yourself. For layerindex that is over-engineering.

## Applying phase 2

The code is already in the tree and inert until `OIDC_RP_CLIENT_ID` is set.
Configure and rebuild (`dc` alias from phase 1, step 4):

```sh
$EDITOR .env      # AUTHENTIK_URL, AUTHENTIK_APP_SLUG, OIDC_RP_CLIENT_ID/SECRET,
                  # OIDC_STAFF_GROUPS, OIDC_SUPERUSER_GROUPS
dc up -d --build
```

Routes added: `oidc/authenticate/`, `oidc/callback/`, `oidc/logout/`. Nothing
under `accounts/` moves.

### Closing local registration

Once SSO is authoritative, set `REGISTRATION_OPEN=0` in `.env`. Verified against
django-registration 5.2.1: `RegistrationView.registration_allowed()` reads
`settings.REGISTRATION_OPEN` and redirects to the `django_registration_disallowed`
URL, and `CaptchaRegistrationView` subclasses it, so layerindex's custom view
honours it too. **The package does not ship
`django_registration/registration_closed.html`** — without the template supplied
here you get a `TemplateDoesNotExist` 500 instead of a clean page.

Leaving registration open alongside SSO is the riskier configuration: it lets
someone create a local account with an SSO user's email address and collide with
the email-based linking.

### Existing local accounts

Nothing breaks. Local login, security-question reset and the admin all keep
working. Users who log in via SSO with a matching verified email are linked to
their existing account on first SSO login and keep all their layer maintainer
associations. `UserProfile` and security-question rows are only created by the
registration flow, so SSO-created users have none — every access to
`user.userprofile` in the codebase is already guarded with
`UserProfile.DoesNotExist`, so this is fine; those users simply never use the
security-question reset path (they have an unusable password).

One behaviour to be deliberate about: if `OIDC_SUPERUSER_GROUPS` is set, a local
superuser who logs in via SSO and is *not* in that Authentik group will be
demoted. That is the correct semantics for an authoritative IdP, but keep one
local break-glass superuser whose email is not in Authentik.

### DRF API

Leave it anonymous and read-only. It is a public data feed and every existing
consumer depends on that. If you later need authenticated writes,
`mozilla_django_oidc.contrib.drf.OIDCAuthentication` validates bearer access
tokens against the userinfo endpoint; plain DRF `TokenAuthentication` is the
pragmatic answer for machine accounts (and note axes does not cover token auth,
which is fine).

---

## Verification performed

- `caddy validate --adapter caddyfile` against the real **caddy 2.11.7** binary:
  *Valid configuration*; file is `caddy fmt`-clean.
- `Dockerfile.caddy` builds against **caddy 2.11.7**, `http.handlers.rate_limit`
  is listed, and the Caddyfile validates with the `rate_limit` block enabled.
- `docker compose config` against **Compose v5.4.0**: renders, anchors resolve,
  build context resolves to the repo root.
- `docker/settings.py` executed under **Django
  5.2.17** with OIDC env set and unset — endpoints, group lists, backend order
  and `INSTALLED_APPS` all correct in both states, no OIDC settings leaking when
  disabled.
- `layerindex/oidc.py` imported and exercised against real **mozilla-django-oidc
  5.0.2**: backend instantiates, `verify_claims` rejects missing and unverified
  email, `provider_logout` produces the expected end-session URL.
- Both templates parse under the Django template engine.
- `RegistrationView.registration_allowed()` reading `REGISTRATION_OPEN`, and the
  absence of a `registration_closed.html` template, confirmed by reading the
  django-registration 5.2.1 sdist.
- `OIDCAuthenticationBackend.authenticate()` returning `None` without
  `code`/`state` — the property the backend ordering depends on — confirmed by
  reading the 5.0.2 wheel.
- `mozilla-django-oidc` 5.0.2 (wheel and sdist) is available on the safetycli
  index that `requirements.txt` pins.
- End-to-end deployment on a Hetzner VM (`layers.moto-timo.io`, October 2026):
  staging and then production certificates issued over IPv4 and IPv6, site and
  API served over HTTPS, celery worker running.

## Not verified

- Actual `LAYER_FETCH_DIR` size (60–120 GB is an estimate from 622 layers /
  ~400 repos; measure after the first full update run).

## Sources

**Caddy** — [Automatic HTTPS](https://caddyserver.com/docs/automatic-https) ·
[reverse_proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy) ·
[handle_path](https://caddyserver.com/docs/caddyfile/directives/handle_path) ·
[encode](https://caddyserver.com/docs/caddyfile/directives/encode) ·
[tls](https://caddyserver.com/docs/caddyfile/directives/tls) ·
[global options](https://caddyserver.com/docs/caddyfile/options) ·
[Docker image](https://hub.docker.com/_/caddy) ·
[releases](https://github.com/caddyserver/caddy/releases) ·
[caddy-ratelimit](https://github.com/mholt/caddy-ratelimit)

**Let's Encrypt** — [rate limits](https://letsencrypt.org/docs/rate-limits/) ·
[staging environment](https://letsencrypt.org/docs/staging-environment/)

**Hetzner** — [Cloud servers FAQ (SMTP blocking)](https://docs.hetzner.com/cloud/servers/faq/) ·
[Cloud Firewalls](https://docs.hetzner.com/cloud/firewalls/overview/) ·
[Primary IPs](https://docs.hetzner.com/cloud/servers/primary-ips/overview/) ·
[rDNS](https://docs.hetzner.com/cloud/servers/cloud-server-rdns/) ·
[Backups & snapshots](https://docs.hetzner.com/cloud/servers/backups-snapshots/overview/) ·
[Volumes](https://docs.hetzner.com/cloud/volumes/overview/) ·
[June 2026 price adjustment](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/)

**Authentik** — [OAuth2/OIDC provider](https://docs.goauthentik.io/add-secure-apps/providers/oauth2/) ·
[create an OAuth2 provider](https://docs.goauthentik.io/add-secure-apps/providers/oauth2/create-oauth2-provider/) ·
[property mappings](https://docs.goauthentik.io/add-secure-apps/providers/property-mappings/) ·
[front/back-channel logout](https://docs.goauthentik.io/add-secure-apps/providers/oauth2/frontchannel_and_backchannel_logout/) ·
[forward auth with Caddy](https://docs.goauthentik.io/add-secure-apps/providers/proxy/server_caddy/) ·
[2026.5 release notes](https://docs.goauthentik.io/releases/2026.5/) ·
[issue #19201](https://github.com/goauthentik/authentik/issues/19201) ·
[GHSA-7jxf-mmg9-9hg7](https://github.com/goauthentik/authentik/security/advisories/GHSA-7jxf-mmg9-9hg7)

**Django side** — [mozilla-django-oidc settings](https://mozilla-django-oidc.readthedocs.io/en/stable/settings.html) ·
[DRF integration](https://mozilla-django-oidc.readthedocs.io/en/stable/drf.html) ·
[django-allauth OIDC provider](https://docs.allauth.org/en/dev/socialaccount/providers/openid_connect.html) ·
[django-axes integration](https://django-axes.readthedocs.io/en/stable/6_integration.html) ·
[Django REMOTE_USER howto](https://docs.djangoproject.com/en/5.2/howto/auth-remote-user/)
