#!/usr/bin/env python3

#
# Create a new release (and its milestones) from a YAML file.
#
# Licensed under the MIT license, see COPYING.MIT for details
#
# SPDX-License-Identifier: MIT

import sys
import os.path

sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), '..', '..', 'layerindex')))

import argparse
import utils
import logging
import yaml

logger = utils.logger_create('CreateRelease')


def main():
    parser = argparse.ArgumentParser(
        description="Create a new release and milestones from a YAML file",
        epilog="""Example YAML file:

  release:
    plan: "OE-Core"
    name: 5.1
    start_date: 2024-04-30
    end_date: 2024-10-25
    milestones:
      - name: M1
        start_date: 2024-04-30
        end_date: 2024-05-31
      - name: M2
        start_date: 2024-06-03
        end_date: 2024-07-19
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("yamlfile", help="Path to YAML file defining the release")
    parser.add_argument('-d', '--debug', action='store_true',
                        help='Enable debug output')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='Hide all output except error messages')
    parser.add_argument('-n', '--dry-run', action='store_true',
                        help='Do not write any changes')
    parser.add_argument('--update', action='store_true',
                        help='Update existing release/milestones if they already exist')

    args = parser.parse_args()

    if args.debug:
        loglevel = logging.DEBUG
    elif args.quiet:
        loglevel = logging.WARNING
    else:
        loglevel = logging.INFO

    logger.setLevel(loglevel)

    with open(args.yamlfile, 'r') as f:
        data = yaml.safe_load(f)

    if 'release' not in data:
        logger.error("YAML file must contain a top-level 'release' key")
        sys.exit(1)

    reldata = data['release']

    for field in ('plan', 'name', 'start_date', 'end_date'):
        if field not in reldata:
            logger.error("Release is missing required field '%s'" % field)
            sys.exit(1)

    milestones = reldata.get('milestones', [])
    for i, ms in enumerate(milestones):
        for field in ('name', 'start_date', 'end_date'):
            if field not in ms:
                logger.error("Milestone %d is missing required field '%s'"
                             % (i + 1, field))
                sys.exit(1)

    utils.setup_django()
    from rrs.models import MaintenancePlan, Release, Milestone
    from django.db import transaction

    plan_name = str(reldata['plan'])
    maintplan = MaintenancePlan.objects.filter(name=plan_name).first()
    if not maintplan:
        logger.error("Maintenance plan '%s' does not exist. Available plans: %s"
                     % (plan_name,
                        ', '.join(MaintenancePlan.objects.values_list('name', flat=True))))
        sys.exit(1)

    release_name = str(reldata['name'])

    try:
        with transaction.atomic():
            existing = Release.objects.filter(plan=maintplan,
                                             name=release_name).first()
            if existing:
                if not args.update:
                    logger.error("Release '%s' already exists for plan '%s' "
                                 "(use --update to update it)" % (release_name, plan_name))
                    sys.exit(1)
                release = existing
                release.start_date = reldata['start_date']
                release.end_date = reldata['end_date']
                release.save()
                logger.info("Updated release '%s'" % release)
            else:
                release = Release.objects.create(
                    plan=maintplan,
                    name=release_name,
                    start_date=reldata['start_date'],
                    end_date=reldata['end_date'],
                )
                logger.info("Created release '%s'" % release)

            for ms in milestones:
                ms_name = str(ms['name'])
                existing_ms = Milestone.objects.filter(release=release,
                                                      name=ms_name).first()
                if existing_ms:
                    if not args.update:
                        logger.error("Milestone '%s' already exists for release "
                                     "'%s' (use --update to update it)"
                                     % (ms_name, release))
                        sys.exit(1)
                    existing_ms.start_date = ms['start_date']
                    existing_ms.end_date = ms['end_date']
                    existing_ms.save()
                    logger.info("Updated milestone '%s'" % existing_ms)
                else:
                    milestone = Milestone.objects.create(
                        release=release,
                        name=ms_name,
                        start_date=ms['start_date'],
                        end_date=ms['end_date'],
                    )
                    logger.info("Created milestone '%s'" % milestone)

            if args.dry_run:
                raise DryRunRollbackException
    except DryRunRollbackException:
        logger.info("Dry run; changes not saved")

    sys.exit(0)


class DryRunRollbackException(Exception):
    pass


if __name__ == "__main__":
    main()
