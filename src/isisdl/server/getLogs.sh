#!/bin/bash

ssh_name="root@hetzner-vserver"
rsync -r "$ssh_name:/home/isisdl-server/isisdl/src/isisdl/server/logs/" "logs"
