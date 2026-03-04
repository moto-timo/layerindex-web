#!/usr/bin/env python3

# Disable updates on the master branch for layers that do not set
# LAYERSERIES_COMPAT in their layer.conf, and add a warning note.
#
# Copyright (C) 2026 Konsulko Group
# Author: Tim Orling <tim.orling@konsulko.com>
#
# Licensed under the MIT license, see COPYING.MIT for details
#
# SPDX-License-Identifier: MIT

import sys
import os
import re

sys.path.insert(0, os.path.realpath(os.path.dirname(__file__)))

import optparse
from layerindex import utils
import logging

class DryRunRollbackException(Exception):
    pass

logger = utils.logger_create('DisableNoLayerseries')

NOTE_TEXT = "This layer does not set LAYERSERIES_COMPAT in its layer.conf and is no longer being updated."


def has_layerseries_compat(layerconf_path):
    """Check if a layer.conf file sets LAYERSERIES_COMPAT."""
    try:
        with open(layerconf_path, 'r') as f:
            content = f.read()
    except FileNotFoundError:
        return False

    # Match LAYERSERIES_COMPAT_<collection> assignment (= or .= or += or ?= etc.)
    # accounting for possible spaces and different assignment operators
    match = re.search(r'^LAYERSERIES_COMPAT_\S+\s*[\+\.\?]*=', content, re.MULTILINE)
    if match:
        logger.debug("Found: %s" % match.group(0))
        return True
    return False


def main():
    parser = optparse.OptionParser(
        usage = """
    %prog [options]

Disable updates on the master branch for any layer that does not set
LAYERSERIES_COMPAT in its layer.conf. Also adds a warning note to
any disabled layer.""")

    parser.add_option("-n", "--dry-run",
            help = "Don't write any data back to the database",
            action="store_true", dest="dryrun")
    parser.add_option("-d", "--debug",
            help = "Enable debug output",
            action="store_const", const=logging.DEBUG, dest="loglevel", default=logging.INFO)
    parser.add_option("-q", "--quiet",
            help = "Hide all output except error messages",
            action="store_const", const=logging.ERROR, dest="loglevel")
    parser.add_option("-b", "--branch",
            help = "Branch to check (default: master)",
            action="store", dest="branch", default="master")

    options, args = parser.parse_args(sys.argv)

    utils.setup_django()
    import settings
    from layerindex.models import Branch, LayerItem, LayerBranch, LayerNote
    from django.db import transaction

    logger.setLevel(options.loglevel)

    fetchdir = settings.LAYER_FETCH_DIR
    if not fetchdir:
        logger.error("Please set LAYER_FETCH_DIR in settings.py")
        sys.exit(1)

    branch = utils.get_branch(options.branch)
    if not branch:
        logger.error("Specified branch %s is not valid" % options.branch)
        sys.exit(1)

    core_layer_name = getattr(settings, 'CORE_LAYER_NAME', 'openembedded-core')

    disabled_count = 0
    skipped_count = 0
    ok_count = 0

    try:
        with transaction.atomic():
            layerbranches = LayerBranch.objects.filter(
                branch=branch,
                layer__status='P',
                layer__comparison=False,
                updates_enabled=True
            ).select_related('layer')

            for layerbranch in layerbranches:
                layer = layerbranch.layer

                # Skip the core layer - it defines LAYERSERIES_COMPAT for others
                if layer.name == core_layer_name:
                    logger.debug("Skipping core layer %s" % layer.name)
                    continue

                urldir = layer.get_fetch_dir()
                repodir = os.path.join(fetchdir, urldir)
                layerdir = repodir
                if layerbranch.vcs_subdir:
                    layerdir = os.path.join(repodir, layerbranch.vcs_subdir)

                layerconf_path = os.path.join(layerdir, 'conf', 'layer.conf')

                if not os.path.exists(layerconf_path):
                    logger.warning("layer.conf not found for %s at %s, skipping" % (layer.name, layerconf_path))
                    skipped_count += 1
                    continue

                if has_layerseries_compat(layerconf_path):
                    logger.debug("%s: LAYERSERIES_COMPAT is set, OK" % layer.name)
                    ok_count += 1
                    continue

                logger.info("Disabling updates for %s (branch %s) - no LAYERSERIES_COMPAT" % (layer.name, options.branch))
                layerbranch.updates_enabled = False
                layerbranch.save()

                # Add a note if one doesn't already exist with the same text
                existing_note = LayerNote.objects.filter(layer=layer, text=NOTE_TEXT).first()
                if not existing_note:
                    note = LayerNote(layer=layer, text=NOTE_TEXT)
                    note.save()
                    logger.info("  Added warning note to %s" % layer.name)

                disabled_count += 1

            logger.info("Summary: %d disabled, %d OK, %d skipped" % (disabled_count, ok_count, skipped_count))

            if options.dryrun:
                raise DryRunRollbackException()
    except DryRunRollbackException:
        logger.info("Dry run - no changes committed to database")

    sys.exit(0)


if __name__ == "__main__":
    main()
