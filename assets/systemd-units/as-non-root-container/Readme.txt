### Systemd User Units for Podman Containers (py-phone-caller 1.0.0)

Place these unit files in your user systemd directory:
`~/.config/systemd/user/`

To install and enable all services as a non-root user:

```bash
mkdir -p ~/.config/systemd/user/
cp assets/systemd-units/as-non-root-container/*.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now \
  container-postgres.service \
  container-redis.service \
  container-caller_register.service \
  container-caller_address_book.service \
  container-generate_audio.service \
  container-asterisk_caller.service \
  container-asterisk_ws_monitor.service \
  container-asterisk_recaller.service \
  container-caller_sms.service \
  container-caller_prometheus_webhook.service \
  container-caller_scheduler.service \
  container-py_phone_caller_ui.service \
  container-celery_worker.service
```

To allow user services to start on boot without requiring an interactive login:

```bash
loginctl enable-linger $USER
```
