# Moving a layer index from MariaDB to PostgreSQL

The layer index runs on MariaDB (the default) or PostgreSQL, chosen by
`DATABASE_ENGINE` in the application's environment (`mysql` or `postgresql`,
see `docker/settings.py`). A new installation can start on PostgreSQL with
`./dockersetup.py --database postgresql`. This document moves an existing
Docker installation's data across, keeping MariaDB untouched so that you can
switch back.

Rehearse the whole procedure on a copy of the production database first, and
check the result before doing it for real.

The commands below use the service names of the repository's
`docker-compose.yml`: `layersdb` (MariaDB), `layersapp` and `layerscelery`. The
PostgreSQL service added in step 2 is called `layerspostgres`.

## 1. Check for values that differ only in case

MariaDB compares text without case, so its unique fields can't hold two values
that differ only in case. PostgreSQL compares with case, so after the move
such values can be created. Check that the existing data has none:

```sh
docker compose run --rm layersapp /opt/layerindex/layerindex/tools/check_case_duplicates.py
```

Searches in the layer index ignore case on both databases. Logging in does
not: on PostgreSQL a user name has to be typed with the same case it was
registered with.

## 2. Add a PostgreSQL server

Add a service next to `layersdb` in `docker-compose.yml`, with a volume for its
data:

```yaml
  layerspostgres:
    image: postgres:17
    environment:
      - POSTGRES_DB=layersdb
      - POSTGRES_PASSWORD=<a new password>
    volumes:
      - layerspgdata:/var/lib/postgresql/data
    restart: unless-stopped
```

and `layerspgdata:` under the top-level `volumes:`. Then start it:

```sh
docker compose up -d layerspostgres
```

## 3. Create the schema

Run the migrations against PostgreSQL as its `postgres` user:

```sh
docker compose run --rm -e DATABASE_ENGINE=postgresql -e DATABASE_HOST=layerspostgres -e DATABASE_USER=postgres -e DATABASE_PASSWORD='<postgres password>' layersapp /opt/migrate.sh
```

Then create the `layers` user that the application connects as. The grants
also cover the tables that later migrations create:

```sh
docker compose exec -T layerspostgres psql -U postgres -d layersdb <<'EOF'
CREATE USER layers WITH PASSWORD '<application password>';
GRANT SELECT, UPDATE, INSERT, DELETE ON ALL TABLES IN SCHEMA public TO layers;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO layers;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT SELECT, UPDATE, INSERT, DELETE ON TABLES TO layers;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO layers;
EOF
```

## 4. Stop everything that writes

```sh
docker compose stop layersapp layerscelery
```

Also stop or disable whatever runs layer updates and the RRS tools (cron
jobs or systemd timers), and wait for a running one to finish. Then back up
MariaDB as described in README.md ("Backup and restore").

## 5. Copy the data

`copy_mariadb_to_postgresql.py` empties every PostgreSQL table, copies each one
from MariaDB with its ids, resets the id sequences, and then compares the two
databases: the row count of every table, digests of the text, boolean and
date columns of the main tables, and the sequences.

```sh
docker compose run --rm --no-deps -e DATABASE_USER=root -e DATABASE_PASSWORD='<MariaDB root password>' -e PG_USER=postgres -e PG_PASSWORD='<postgres password>' layersapp /opt/layerindex/layerindex/tools/copy_mariadb_to_postgresql.py layersdb layerspostgres
```

It should end with `0 problems found`. A copy of production takes a few
minutes. Lines starting `NOTE:` list tables that exist in only one of the
databases (MariaDB can still have tables from applications the layer index no
longer uses; they are not copied) and text values from which a NUL character
was removed, which PostgreSQL can't store.

To copy again into the same database, add `--replace`; without it the script
refuses to empty a database that already has data. `--verify` repeats the
comparison without copying.

## 6. Switch over

Add to `.env.local.app` and `.env.local.celery`:

```
DATABASE_ENGINE=postgresql
DATABASE_HOST=layerspostgres
```

and, if the password of the `layers` user differs from the MariaDB one, change
`DATABASE_PASSWORD` there too. Then start the application again:

```sh
docker compose up -d layersapp layerscelery
```

Check the front page, a layer, a recipe search, the admin pages and, if RRS is
enabled, its recipe list. Then turn layer updates back on.

## Switching back

MariaDB is not changed by any of this. To go back, remove the two lines from
step 6 and restart `layersapp` and `layerscelery`. Anything written since the
switch is then lost, unless you copy it back yourself.

---

Based on the migration runbook in Michael Halstead's PostgreSQL branch.
