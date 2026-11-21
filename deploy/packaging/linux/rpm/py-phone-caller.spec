Name:           py-phone-caller
Version:        1.0.0
Release:        1%{?dist}
Summary:        Automated phone call and SMS alerting platform for Asterisk PBX
License:        BSD-3-Clause
URL:            https://github.com/jcfdeb/py-phone-caller
BuildArch:      noarch
Requires:       bash, shadow-utils, systemd

%description
py-phone-caller is a Python-based alerting platform that turns monitoring and
operational events into outbound phone calls and SMS messages through Asterisk
PBX, Twilio, and on-premise USB GSM modems.

%install
cp -a %{buildroot_source}/* %{buildroot}/

%pre
getent group py-phone-caller >/dev/null || groupadd -r py-phone-caller
getent passwd py-phone-caller >/dev/null || \
    useradd -r -g py-phone-caller -d /opt/py-phone-caller -s /sbin/nologin \
    -c "py-phone-caller service account" py-phone-caller
exit 0

%post
chown -R py-phone-caller:py-phone-caller /opt/py-phone-caller /etc/py-phone-caller || true
systemctl daemon-reload >/dev/null 2>&1 || true

%preun
if [ $1 -eq 0 ]; then
    systemctl stop py-phone-caller.target >/dev/null 2>&1 || true
fi

%postun
systemctl daemon-reload >/dev/null 2>&1 || true

%files
%defattr(-,root,root,-)
/opt/py-phone-caller
%config(noreplace) %attr(0640,root,py-phone-caller) /etc/py-phone-caller/settings.toml
%config(noreplace) %attr(0600,root,py-phone-caller) /etc/py-phone-caller/.secrets.toml.example
/lib/systemd/system/*.service
/lib/systemd/system/py-phone-caller.target
