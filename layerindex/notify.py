# Email notifications about layer updates
#
# Licensed under the MIT license, see COPYING.MIT for details
#
# SPDX-License-Identifier: MIT

from django.conf import settings
from django.contrib.sites.models import Site
from django.core.mail import mail_admins, send_mail
from django.urls import reverse

from layerindex.models import LayerMaintainer, LayerUpdate, UserProfile

# ponytail: fixed thresholds. If more than half of the layer branches in an
# update of at least this many newly fail, something is probably wrong with
# the update itself, not the layers.
SYSTEMIC_MIN_LAYERBRANCHES = 10


def newly_failed(update):
    """Layer updates in this update with errors where the layer branch's
    previous update had none"""
    failed = []
    for layerupdate in LayerUpdate.objects.filter(update=update, errors__gt=0).select_related('layer', 'branch'):
        previous = LayerUpdate.objects.filter(layer=layerupdate.layer, branch=layerupdate.branch,
                                              started__lt=layerupdate.started).order_by('-started').first()
        if not (previous and previous.errors):
            failed.append(layerupdate)
    return failed


def notify_parse_errors(update, logger):
    """Email users who opted in when a layer branch they maintain starts to
    fail, or the site admins instead if most layers did"""
    failed = newly_failed(update)
    if not failed:
        return
    site = Site.objects.get_current()

    def url(layerupdate):
        return 'https://%s%s' % (site.domain, reverse('layerupdate', args=(layerupdate.id,)))

    total = LayerUpdate.objects.filter(update=update).count()
    if total >= SYSTEMIC_MIN_LAYERBRANCHES and len(failed) * 2 > total:
        logger.warning('%d of %d layer branches newly failed; telling the admins instead of the maintainers'
                       % (len(failed), total))
        mail_admins('Layer index update: %d of %d layer branches newly failed' % (len(failed), total),
                    'This is probably a problem with the update rather than with the layers, so no\n'
                    'maintainers were emailed. For example:\n\n%s\n'
                    % '\n'.join('  %s (%s): %s' % (lu.layer.name, lu.branch.name, url(lu)) for lu in failed[:20]))
        return

    subscribers = UserProfile.objects.filter(notify_parse_errors=True, user__is_active=True).select_related('user')
    by_email = {p.user.email.strip().lower(): p.user for p in subscribers if p.user.email}
    for layerupdate in failed:
        maintainers = LayerMaintainer.objects.filter(layerbranch__layer=layerupdate.layer,
                                                     layerbranch__branch=layerupdate.branch, status='A')
        to = sorted({by_email[m.email.strip().lower()].email for m in maintainers
                     if m.email.strip().lower() in by_email})
        if not to:
            continue
        try:
            send_mail('%s (%s) failed to parse on %s' % (layerupdate.layer.name, layerupdate.branch.name, site.name),
                      'The layer index update of %s on the %s branch found %d errors:\n\n  %s\n\n'
                      'You get this email because you maintain this layer and asked to be told when it\n'
                      'starts to fail; you can turn it off on your profile page.\n'
                      % (layerupdate.layer.name, layerupdate.branch.name, layerupdate.errors, url(layerupdate)),
                      settings.DEFAULT_FROM_EMAIL, to)
        except Exception as e:
            logger.warning('Failed to email %s about %s: %s' % (', '.join(to), layerupdate.layer.name, e))
