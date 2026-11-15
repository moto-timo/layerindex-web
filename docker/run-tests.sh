#!/bin/sh
# layerindex-web - run the test suite in the production image against a
# throwaway database: PostgreSQL, or MariaDB with DATABASE_ENGINE=mysql.
# Used by CI; can also be run locally from the repo root.
#
# SPDX-License-Identifier: MIT

set -e

IMAGE=${IMAGE:-layerindex-test}
NET=layerindex-test
DB=layerindex-test-db

docker build -t "$IMAGE" .

docker network create $NET >/dev/null
trap 'docker rm -f $DB >/dev/null; docker network rm $NET >/dev/null' EXIT

# Alias "layersdb" matches the default DATABASE_HOST in docker/settings.py;
# testingpw is that file's default password, not a real secret.
DATABASE_ENGINE=${DATABASE_ENGINE:-postgresql}
case $DATABASE_ENGINE in
postgresql)
    docker run -d --name $DB --network $NET --network-alias layersdb \
        -e POSTGRES_PASSWORD=testingpw postgres:17 >/dev/null
    # Over TCP: the temporary server that initialises the database only
    # listens on the Unix socket
    until docker exec $DB pg_isready -q -h 127.0.0.1 -U postgres >/dev/null 2>&1; do
        sleep 1
    done
    ;;
mysql)
    docker run -d --name $DB --network $NET --network-alias layersdb \
        -e MARIADB_ROOT_PASSWORD=testingpw mariadb:10.11 \
        --character-set-server=utf8mb4 >/dev/null
    until docker exec $DB healthcheck.sh --connect --innodb_initialized >/dev/null 2>&1; do
        sleep 1
    done
    ;;
*)
    echo "DATABASE_ENGINE must be postgresql or mysql" >&2
    exit 1
    ;;
esac

# Runs as root only to prepare the container: tests/test_update.py rewrites
# settings.py and bitbake writes its lock file next to it, the update scripts
# expect bitbake already fetched, and the tests commit to git and call tree.
# ENABLE_RRS=1 so that the tests in tests/rrs/ run and the RRS migrations are
# checked too.
docker run --rm --network $NET -u root \
    -e SECRET_KEY=ci-only -e DATABASE_ENGINE=$DATABASE_ENGINE -e ENABLE_RRS=1 \
    -e GIT_AUTHOR_NAME=ci -e GIT_AUTHOR_EMAIL=ci@example.com \
    -e GIT_COMMITTER_NAME=ci -e GIT_COMMITTER_EMAIL=ci@example.com \
    -v "$PWD/tests:/src/tests:ro" \
    -v "$PWD/requirements-dev.txt:/src/requirements-dev.txt:ro" \
    -w /opt/layerindex "$IMAGE" sh -ec '
        apt-get update -qq && apt-get install -y -qq tree >/dev/null
        cp -r /src/tests /opt/layerindex/
        chown -R layers /opt/layerindex
        su layers -s /bin/sh -c "set -e
            git clone -q https://git.openembedded.org/bitbake /opt/workdir/https___git_openembedded_org_bitbake
            pip3 install -q --user --no-warn-script-location -r /src/requirements-dev.txt
            python3 -m pytest -rfE -p no:cacheprovider tests/
            python3 manage.py makemigrations --check --dry-run rrs"'
