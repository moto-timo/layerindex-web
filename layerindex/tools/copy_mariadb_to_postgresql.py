#!/usr/bin/env python3

# Copy the layer index database from MariaDB to PostgreSQL, and check the copy
#
# The PostgreSQL schema must already exist: run "manage.py migrate" with
# DATABASE_ENGINE=postgresql first. Every PostgreSQL table except
# django_migrations is then emptied and filled from the MariaDB table of the
# same name, keeping the ids. Afterwards the id sequences are reset and the
# copy is checked: row counts of every table, digests of the columns most
# likely to differ (text, booleans, dates), and the id sequences.
#
# Stop the application, the Celery worker and any layer update while it runs.
#
# Connection settings come from the environment: DATABASE_NAME, DATABASE_USER
# and DATABASE_PASSWORD for MariaDB, and for PostgreSQL the same unless
# PG_NAME, PG_USER or PG_PASSWORD are set. The PostgreSQL user must be allowed
# to set session_replication_role (e.g. the "postgres" superuser), which turns
# off foreign key checks while loading.
#
# Licensed under the MIT license, see COPYING.MIT for details
#
# SPDX-License-Identifier: MIT
#
# AI-generated, Claude Opus 5.5

import argparse
import datetime
import hashlib
import os
import sys
import time

import MySQLdb
import MySQLdb.cursors
import psycopg
from psycopg import sql

SKIP = {'django_migrations'}
BATCH = 5000

# Whole-table (or sampled) digests compared by check_copy(), ordered by id
DIGESTS = {
    'rrs_maintainer': 'SELECT id, name, email FROM rrs_maintainer ORDER BY id',
    'rrs_recipeupgrade': 'SELECT id, version, prev_version, commit_date, upgrade_type, title '
                         'FROM rrs_recipeupgrade ORDER BY id',
    'rrs_recipeupstream (sample)': 'SELECT id, version, status, no_update_reason, date '
                                   'FROM rrs_recipeupstream WHERE id % 97 = 0 ORDER BY id',
    'layerindex_layeritem': 'SELECT id, name, status, layer_type, summary, description, comparison, '
                            'published FROM layerindex_layeritem ORDER BY id',
    'layerindex_layerbranch': 'SELECT id, layer_id, branch_id, vcs_subdir, vcs_last_rev, updates_enabled, '
                              'yp_compatible_version_id FROM layerindex_layerbranch ORDER BY id',
    'layerindex_branch': 'SELECT id, name, sort_priority, updates_enabled, comparison, hidden '
                         'FROM layerindex_branch ORDER BY id',
    'layerindex_recipe (sample)': 'SELECT id, pn, pv, summary, description, license, homepage, updated '
                                  'FROM layerindex_recipe WHERE id % 13 = 0 ORDER BY id',
    'auth_user': 'SELECT id, username, email, is_staff, is_active, is_superuser, date_joined, password '
                 'FROM auth_user ORDER BY id',
    'layerindex_layermaintainer': 'SELECT id, layerbranch_id, name, email, responsibility, status '
                                  'FROM layerindex_layermaintainer ORDER BY id',
}


def convert_row(row, booleans, texts):
    """Turn a MariaDB row into one PostgreSQL accepts.

    Returns the row and how many text values had NUL characters removed.
    """
    row = list(row)
    nul = 0
    for i in booleans:
        # MariaDB stores booleans as 0/1
        if row[i] is not None:
            row[i] = bool(row[i])
    for i in texts:
        # PostgreSQL text can't hold NUL
        if row[i] and '\x00' in row[i]:
            row[i] = row[i].replace('\x00', '')
            nul += 1
    return row, nul


def normalise(value):
    """Make a value read from either database compare equal"""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, str):
        # convert_row() removed NUL from the copy
        return value.replace('\x00', '')
    if isinstance(value, datetime.datetime) and value.tzinfo:
        # timestamptz comes back in the connection's time zone
        return value.astimezone(datetime.UTC).replace(tzinfo=None)
    return value


def db_settings():
    name = os.getenv('DATABASE_NAME', 'layersdb')
    user = os.environ['DATABASE_USER']
    password = os.environ['DATABASE_PASSWORD']
    return name, user, password


def table_lists(mycur, pgcur):
    mycur.execute('SHOW TABLES')
    my_tables = {r[0] for r in mycur.fetchall()}
    pgcur.execute("SELECT table_name FROM information_schema.tables "
                  "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'")
    pg_tables = {r[0] for r in pgcur.fetchall()} - SKIP
    return my_tables - SKIP, pg_tables


def copy_tables(my, pg, replace):
    mycur = my.cursor()
    with pg.cursor() as cur:
        my_tables, pg_tables = table_lists(mycur, cur)
        tables = sorted(pg_tables & my_tables)
        for t in sorted(my_tables - pg_tables):
            print(f'NOTE: only in MariaDB, not copied: {t}')
        for t in sorted(pg_tables - my_tables):
            print(f'NOTE: only in PostgreSQL, left empty: {t}')

        # Refuse to overwrite a database in use unless asked to
        cur.execute("SELECT EXISTS (SELECT 1 FROM layerindex_layeritem)")
        if cur.fetchone()[0] and not replace:
            print('ERROR: the PostgreSQL database already has data; use --replace to empty it',
                  file=sys.stderr)
            return None

        cur.execute(sql.SQL('TRUNCATE {} RESTART IDENTITY CASCADE').format(
            sql.SQL(', ').join(sql.Identifier(t) for t in sorted(pg_tables))))
        # No foreign key checks while loading, so the order doesn't matter
        cur.execute('SET session_replication_role = replica')
    pg.commit()

    for table in tables:
        t0 = time.time()
        with pg.cursor() as cur:
            cur.execute("SELECT column_name, data_type FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position",
                        (table,))
            pg_cols = cur.fetchall()
        mycur.execute(f'SHOW COLUMNS FROM `{table}`')
        my_cols = {r[0] for r in mycur.fetchall()}
        cols = [(c, ty) for c, ty in pg_cols if c in my_cols]
        missing = [c for c, ty in pg_cols if c not in my_cols]
        extra = sorted(my_cols - {c for c, ty in pg_cols})
        if missing or extra:
            print(f'NOTE: {table}: columns only in PostgreSQL {missing}, only in MariaDB {extra}')
        booleans = [i for i, (c, ty) in enumerate(cols) if ty == 'boolean']
        texts = [i for i, (c, ty) in enumerate(cols) if ty in ('character varying', 'text')]

        src = my.cursor(MySQLdb.cursors.SSCursor)
        columns = ', '.join(f'`{c}`' for c, ty in cols)
        src.execute(f'SELECT {columns} FROM `{table}`')
        rows = nul = 0
        with pg.cursor() as cur:
            copy_sql = sql.SQL('COPY {} ({}) FROM STDIN').format(
                sql.Identifier(table), sql.SQL(', ').join(sql.Identifier(c) for c, ty in cols))
            with cur.copy(copy_sql) as copy:
                while batch := src.fetchmany(BATCH):
                    for row in batch:
                        row, n = convert_row(row, booleans, texts)
                        nul += n
                        copy.write_row(row)
                    rows += len(batch)
        src.close()
        pg.commit()
        note = f' ({nul} values had NUL removed)' if nul else ''
        print(f'{table:50} {rows:9d} rows {time.time() - t0:6.1f}s{note}', flush=True)

    # Restart each id sequence after the highest id copied
    with pg.cursor() as cur:
        cur.execute("SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND (is_identity = 'YES' "
                    "OR column_default LIKE 'nextval%%')")
        for table, col in cur.fetchall():
            cur.execute(sql.SQL("SELECT setval(pg_get_serial_sequence(%s, %s), "
                                "COALESCE(MAX({}), 1), MAX({}) IS NOT NULL) FROM {}").format(
                sql.Identifier(col), sql.Identifier(col), sql.Identifier(table)),
                (table, col))
    pg.commit()
    return tables


def digest(cur, query):
    cur.execute(query)
    h = hashlib.sha256()
    n = 0
    for row in cur.fetchall():
        h.update(repr(tuple(normalise(v) for v in row)).encode())
        n += 1
    return n, h.hexdigest()[:16]


def check_copy(my, pg):
    """Compare the two databases; return the number of problems found"""
    mycur = my.cursor()
    bad = 0
    with pg.cursor() as cur:
        my_tables, pg_tables = table_lists(mycur, cur)
        for table in sorted(pg_tables & my_tables):
            mycur.execute(f'SELECT COUNT(*) FROM `{table}`')
            n_my = mycur.fetchone()[0]
            cur.execute(sql.SQL('SELECT COUNT(*) FROM {}').format(sql.Identifier(table)))
            n_pg = cur.fetchone()[0]
            if n_my != n_pg:
                print(f'MISMATCH {table}: MariaDB {n_my} rows, PostgreSQL {n_pg}')
                bad += 1

        for label, query in DIGESTS.items():
            if label.split()[0] not in pg_tables & my_tables:
                continue
            a, b = digest(mycur, query), digest(cur, query)
            if a != b:
                bad += 1
            print(f'{label:32} {"same" if a == b else "DIFFERENT"}  MariaDB {a}  PostgreSQL {b}')

        # Each id sequence must continue after the highest id
        cur.execute("SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND (is_identity = 'YES' "
                    "OR column_default LIKE 'nextval%%')")
        for table, col in cur.fetchall():
            cur.execute(sql.SQL("SELECT COALESCE(MAX({}), 0), "
                                "nextval(pg_get_serial_sequence(%s, %s)) FROM {}").format(
                sql.Identifier(col), sql.Identifier(table)), (table, col))
            mx, nxt = cur.fetchone()
            if nxt <= mx:
                print(f'STALE SEQUENCE {table}.{col}: next {nxt}, highest {mx}')
                bad += 1
    # nextval() moved the sequences on; leaving gaps in the ids is harmless
    pg.commit()
    return bad


def main():
    parser = argparse.ArgumentParser(description='Copy the layer index database from MariaDB '
                                                 'to PostgreSQL, then check the copy.')
    parser.add_argument('mysql_host', help='MariaDB host')
    parser.add_argument('pg_host', help='PostgreSQL host')
    parser.add_argument('--replace', action='store_true',
                        help='empty the PostgreSQL database even if it already has data')
    parser.add_argument('--verify', action='store_true', help='only check an earlier copy')
    args = parser.parse_args()

    name, user, password = db_settings()
    # utf8mb4 on the connection: the server converts latin1 tables to UTF-8
    # as it reads them
    my = MySQLdb.connect(host=args.mysql_host, user=user, password=password, database=name,
                         charset='utf8mb4', use_unicode=True)
    pg = psycopg.connect(host=args.pg_host, dbname=os.getenv('PG_NAME', name),
                         user=os.getenv('PG_USER', user),
                         password=os.getenv('PG_PASSWORD', password))

    start = time.time()
    if not args.verify:
        tables = copy_tables(my, pg, args.replace)
        if tables is None:
            return 1
        print(f'copied {len(tables)} tables in {time.time() - start:.0f}s')
    bad = check_copy(my, pg)
    print(f'{bad} problems found')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
