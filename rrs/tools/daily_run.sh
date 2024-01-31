#!/bin/bash

/opt/layerindex/layerindex/update.py -q
/opt/layerindex/rrs/tools/rrs_maintainer_history.py -d
/opt/layerindex/rrs/tools/rrs_upgrade_history.py -d
/opt/layerindex/rrs/tools/rrs_upstream_history.py -d
# FIXME: requires changes in meta/lib/oe/distro_check.py to be functional
#/opt/layerindex/rrs/tools/rrs_distros.py -d

if [ "$1" = "email" ]; then
	/opt/layerindex/rrs/tools/rrs_upstream_email.py
fi
