#!/bin/sh
# Prepare a fresh Hetzner Cloud VM (Debian 12/13 or Ubuntu 24.04) to run the
# layerindex stack. Run as root, once, before the first `docker compose up`.
#
#   scp deploy/hetzner/bootstrap-host.sh root@<ip>:/root/
#   ssh root@<ip> sh /root/bootstrap-host.sh
#
# Deliberately does NOT configure a host firewall: Docker's iptables rules
# bypass ufw/firewalld for published ports, which gives false confidence. Use
# the Hetzner Cloud Firewall instead (see deploy/README.md).
#
# SPDX-License-Identifier: MIT
set -eu

echo "==> base packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
	ca-certificates curl git gnupg unattended-upgrades

echo "==> docker engine + compose plugin (official repo)"
install -m 0755 -d /etc/apt/keyrings
. /etc/os-release
curl -fsSL "https://download.docker.com/linux/${ID}/gpg" \
	-o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/%s %s stable\n' \
	"$(dpkg --print-architecture)" "${ID}" "${VERSION_CODENAME}" \
	> /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io \
	docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker

echo "==> log rotation for containers"
cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "50m", "max-file": "5" }
}
EOF
systemctl restart docker

echo "==> unattended security upgrades"
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "==> sshd hardening (key auth only)"
cat > /etc/ssh/sshd_config.d/99-layerindex.conf <<'EOF'
PasswordAuthentication no
PermitRootLogin prohibit-password
EOF
systemctl reload ssh 2>/dev/null || systemctl reload sshd

echo "==> swap (bitbake parsing is memory-bursty)"
if [ ! -f /swapfile ]; then
	fallocate -l 4G /swapfile
	chmod 600 /swapfile
	mkswap /swapfile
	swapon /swapfile
	echo '/swapfile none swap sw 0 0' >> /etc/fstab
	sysctl -w vm.swappiness=10
	echo 'vm.swappiness=10' > /etc/sysctl.d/99-swappiness.conf
fi

echo
echo "Done. Next:"
echo "  1. Point DNS at this host and verify:  dig +short <hostname>"
echo "  2. Attach a Hetzner Cloud Firewall: inbound TCP 22 (your IPs), TCP 80,"
echo "     TCP 443, UDP 443 -- each with BOTH 0.0.0.0/0 and ::/0 sources."
echo "  3. git clone the layerindex-web repo, cp deploy/hetzner/env.example .env"
echo "  4. docker compose -f deploy/hetzner/docker-compose.yml up -d --build"
