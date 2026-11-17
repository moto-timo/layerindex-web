#!/bin/sh

# Dump database without user tables (for the purpose of creating a dump
# that can be imported into a fresh database)
#
# Copyright (C) 2019 Intel Corporation
# Author: Paul Eggleton <paul.eggleton@linux.intel.com>
#
# Licensed under the MIT license, see COPYING.MIT for details

if [ "$1" = "" ] ; then
    echo "Please specify a database"
    exit 1
fi

if [ "$2" = "" ] ; then
    echo "Please specify an output file (.sql)"
    exit 1
fi

if [ -f $2 ] ; then
    echo "File $2 already exists"
    exit 1
fi

if [ -f $2.gz ] ; then
    echo "File $2.gz already exists"
    exit 1
fi

# Tables left out of the data: users and their data, sessions, logs, and the
# RRS data, which is specific to each installation
EXCLUDE="\
    auth_group \
    auth_group_permissions \
    auth_permission \
    auth_user \
    auth_user_groups \
    auth_user_user_permissions \
    layerindex_userprofile \
    layerindex_securityquestionanswer \
    layerindex_sitenotice \
    layerindex_layerupdate \
    layerindex_update \
    reversion_revision \
    reversion_version \
    rrs_maintainer \
    rrs_maintenanceplan \
    rrs_maintenanceplanlayerbranch \
    rrs_milestone \
    rrs_recipedistro \
    rrs_recipemaintainer \
    rrs_recipemaintainerhistory \
    rrs_recipemaintenancelink \
    rrs_recipeupgrade \
    rrs_recipeupstream \
    rrs_recipeupstreamhistory \
    rrs_release \
    django_session \
    django_admin_log \
    axes_accessattempt \
    axes_accesslog \
"

# DATABASE_ENGINE as in docker/settings.py: "mysql" (MariaDB, the default) or
# "postgresql". Each tool asks for the password (PostgreSQL: unless PGPASSWORD
# or ~/.pgpass supplies it); first the structure without data, then the data
# without the tables above.
case "${DATABASE_ENGINE:-mysql}" in
mysql)
    mariadb-dump $1 -u root -p --no-data > $2
    mariadb-dump $1 -u root -p --no-create-info \
        $(for t in $EXCLUDE; do echo "--ignore-table=$1.$t"; done) >> $2
    ;;
postgresql)
    pg_dump $1 -U postgres --schema-only > $2
    pg_dump $1 -U postgres --data-only \
        $(for t in $EXCLUDE; do echo "--exclude-table-data=$t"; done) >> $2
    ;;
*)
    echo "DATABASE_ENGINE must be mysql or postgresql" >&2
    exit 1
    ;;
esac
gzip $2
