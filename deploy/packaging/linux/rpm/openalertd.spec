Name:           openalertd
Version:        1.1.0
Release:        1%{?dist}
Summary:        OpenAlert Daemon - Resilient Multi-Transport Alert Routing
License:        BSD-3-Clause
URL:            https://github.com/jcfdeb/py-phone-caller
Requires:       glibc, systemd, dbus

%description
Decentralized Nostr (NIP-ALERT Kind 30000, NIP-57 Lightning Zap Adapter,
0xChat NIP-17 E2EE C2, Embedded Micro-Relay), /sos Captive Portal, LoRa RF,
and BitChat BLE mesh gateway bridging air-gapped field alerts.

%install
cp -a %{buildroot_source}/* %{buildroot}/

%pre
getent group openalert >/dev/null || groupadd -r openalert
getent passwd openalert >/dev/null || \
    useradd -r -g openalert -d /var/lib/openalertd -s /sbin/nologin \
    -c "OpenAlert Daemon account" openalert
exit 0

%post
mkdir -p /var/lib/openalertd /var/log/openalertd
chown -R openalert:openalert /var/lib/openalertd /var/log/openalertd /etc/openalertd || true
chmod 0750 /var/lib/openalertd /etc/openalertd || true
systemctl daemon-reload >/dev/null 2>&1 || true

%preun
if [ $1 -eq 0 ]; then
    systemctl stop openalertd.service >/dev/null 2>&1 || true
    systemctl disable openalertd.service >/dev/null 2>&1 || true
fi

%postun
systemctl daemon-reload >/dev/null 2>&1 || true

%files
%defattr(-,root,root,-)
%attr(0755,root,root) /usr/local/bin/openalertd
%config(noreplace) %attr(0640,root,openalert) /etc/openalertd/openalertd.toml
/etc/openalertd/profiles
/usr/share/openalertd
/lib/systemd/system/openalertd.service
