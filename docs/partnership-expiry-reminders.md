# Partnership expiry reminders (US-06)

In Makken, open **إدارة الإشعارات** and search for **تذكير بقرب انتهاء الشراكة**. The new rule starts disabled and routes to the employee by default when enabled. It can optionally notify the task manager. A reminder uses the current assignment, not a fixed subscriber list. Each user can still mute it through their existing notification preferences.

The responsible employee comes from **عمل جديد** or **قيد العمل** linked directly to the partnership. Closed tasks and tasks linked only to a sponsorship do not assign responsibility for the partnership's expiry. A recipient needs an active account, valid email and permission to view the partnership.

The reminder becomes due two calendar months before the partnership end date in Riyadh time. When the earlier month is shorter, use its last day (for example, an April 30 expiry is due February 28 in a non-leap year). An hourly scheduler catches up if the first check is missed, as long as the partnership is active and has not reached its end date. No date or valid assignment means no email.

The existing delivery queue allows one entry per partnership, end date and recipient. Delivery checks the date, active partnership, current routing, permissions, email address and mute again just before sending. Changing the end date makes an older queued reminder obsolete and can produce a new reminder for the revised date. Messages appear in **سجل إرسال الإشعارات**.

## Deploy

This update depends on the agreement clause and partnership dates migrations. Deploy the web code and apply migrations via the production container startup before installing the new systemd units. Keep the existing `makken-email-delivery.timer` enabled to send queued mail.

```bash
cd /var/www/html/makken
install -m 0644 tools/systemd/makken-partnership-expiry.{service,timer} /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now makken-partnership-expiry.timer
systemctl list-timers makken-partnership-expiry.timer makken-email-delivery.timer
```

After setting up SMTP, enable the reminder rule. To check for due reminders immediately, run `systemctl start makken-partnership-expiry.service`. This queues any eligible reminders; the existing delivery worker sends them.
