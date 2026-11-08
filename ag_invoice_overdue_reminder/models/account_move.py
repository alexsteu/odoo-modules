import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    overdue_reminder_count = fields.Integer(string="Reminders sent", default=0, copy=False, readonly=True)
    overdue_reminder_last = fields.Date(string="Last reminder", copy=False, readonly=True)
    overdue_reminder_stop = fields.Boolean(
        string="No automatic reminder",
        copy=False,
        help="Tick to never send automatic overdue reminders for this invoice.",
    )

    @api.model
    def _cron_send_overdue_reminders(self):
        template = self.env.ref(
            "ag_invoice_overdue_reminder.mail_template_overdue_reminder",
            raise_if_not_found=False,
        )
        if not template:
            return
        today = fields.Date.context_today(self)
        for company in self.env["res.company"].search([("overdue_reminder_enabled", "=", True)]):
            gap = timedelta(days=max(company.overdue_reminder_days, 1))
            invoices = self.search([
                ("company_id", "=", company.id),
                ("move_type", "=", "out_invoice"),
                ("state", "=", "posted"),
                ("payment_state", "in", ("not_paid", "partial")),
                ("invoice_date_due", "<", today),
                ("overdue_reminder_stop", "=", False),
                ("overdue_reminder_count", "<", company.overdue_reminder_max),
                ("partner_id.email", "!=", False),
            ])
            for invoice in invoices:
                if invoice.overdue_reminder_last and invoice.overdue_reminder_last + gap > today:
                    continue
                try:
                    invoice.message_post_with_source(template, subtype_xmlid="mail.mt_comment")
                    invoice.write({
                        "overdue_reminder_count": invoice.overdue_reminder_count + 1,
                        "overdue_reminder_last": today,
                    })
                    self.env.cr.commit()
                except Exception:
                    self.env.cr.rollback()
                    _logger.exception("Overdue reminder failed for %s", invoice.name)
