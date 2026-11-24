import logging
import threading
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
    overdue_reminder_next = fields.Date(
        string="Next automatic reminder",
        compute="_compute_overdue_reminder_next",
        help="When the next reminder will be e-mailed if the invoice is still unpaid. Empty when none "
             "is planned: invoice paid, reminders stopped, maximum reached or customer without e-mail.",
    )

    def _overdue_reminder_next_dates(self):
        """{invoice id: date of its next automatic reminder}, only for invoices that will get one."""
        result = {}
        for invoice in self:
            company = invoice.company_id
            if (
                invoice.move_type != "out_invoice"
                or invoice.state != "posted"
                or invoice.payment_state not in ("not_paid", "partial")
                or not invoice.invoice_date_due
                or invoice.overdue_reminder_stop
                or not company.overdue_reminder_enabled
                or invoice.overdue_reminder_count >= company.overdue_reminder_max
                or not invoice.partner_id.email
            ):
                continue
            start = company.overdue_reminder_start_date
            if start and invoice.invoice_date_due < start:
                continue            # old unpaid invoices are never chased by surprise
            if invoice.overdue_reminder_last:
                days = max(company.overdue_reminder_days, 1)
                result[invoice.id] = invoice.overdue_reminder_last + timedelta(days=days)
            else:
                # a few days of grace: a transfer made on the due date is not on the bank statement yet
                days = max(company.overdue_reminder_first_days, 1)
                result[invoice.id] = invoice.invoice_date_due + timedelta(days=days)
        return result

    @api.depends("state", "payment_state", "invoice_date_due", "overdue_reminder_stop",
                 "overdue_reminder_count", "overdue_reminder_last", "partner_id")
    def _compute_overdue_reminder_next(self):
        next_dates = self._overdue_reminder_next_dates()
        for invoice in self:
            invoice.overdue_reminder_next = next_dates.get(invoice.id, False)

    @api.model
    def _cron_send_overdue_reminders(self):
        template = self.env.ref(
            "ag_invoice_overdue_reminder.mail_template_overdue_reminder",
            raise_if_not_found=False,
        )
        if not template:
            return
        today = fields.Date.context_today(self)
        # one commit per e-mail: a later failure never sends the same reminder twice
        auto_commit = not getattr(threading.current_thread(), "testing", False)
        companies = self.env["res.company"].search([("overdue_reminder_enabled", "=", True)])
        invoices = self.search([
            ("company_id", "in", companies.ids),
            ("move_type", "=", "out_invoice"),
            ("state", "=", "posted"),
            ("payment_state", "in", ("not_paid", "partial")),
            ("invoice_date_due", "<", today),
            ("overdue_reminder_stop", "=", False),
            ("partner_id.email", "!=", False),
        ])
        next_dates = invoices._overdue_reminder_next_dates()
        for invoice in invoices:
            due = next_dates.get(invoice.id)
            if not due or due > today:
                continue
            try:
                with self.env.cr.savepoint():
                    invoice.message_post_with_source(template, subtype_xmlid="mail.mt_comment")
                    invoice.write({
                        "overdue_reminder_count": invoice.overdue_reminder_count + 1,
                        "overdue_reminder_last": today,
                    })
            except Exception:
                _logger.exception("Overdue reminder failed for %s", invoice.name)
                continue
            if auto_commit:
                self.env.cr.commit()
