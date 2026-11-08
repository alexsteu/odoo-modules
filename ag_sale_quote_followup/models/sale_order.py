import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    followup_count = fields.Integer(string="Follow-ups sent", default=0, copy=False, readonly=True)
    followup_last_date = fields.Datetime(string="Last follow-up", copy=False, readonly=True)
    followup_stop = fields.Boolean(
        string="No automatic follow-up",
        copy=False,
        help="Tick to never send automatic reminders for this quotation.",
    )

    def _followup_reference_date(self):
        self.ensure_one()
        return self.followup_last_date or self.date_order

    @api.model
    def _cron_send_quote_followups(self):
        template = self.env.ref(
            "ag_sale_quote_followup.mail_template_quote_followup", raise_if_not_found=False
        )
        if not template:
            return
        now = fields.Datetime.now()
        for company in self.env["res.company"].search([("quote_followup_enabled", "=", True)]):
            delay = timedelta(days=max(company.quote_followup_days, 1))
            orders = self.search([
                ("company_id", "=", company.id),
                ("state", "=", "sent"),
                ("followup_stop", "=", False),
                ("followup_count", "<", company.quote_followup_max),
                ("partner_id.email", "!=", False),
            ])
            for order in orders:
                if order.validity_date and order.validity_date < now.date():
                    continue
                if order._followup_reference_date() + delay > now:
                    continue
                try:
                    order.with_context(mark_so_as_sent=False).message_post_with_source(
                        template, subtype_xmlid="mail.mt_comment"
                    )
                    order.write({
                        "followup_count": order.followup_count + 1,
                        "followup_last_date": now,
                    })
                    self.env.cr.commit()
                except Exception:
                    self.env.cr.rollback()
                    _logger.exception("Quotation follow-up failed for %s", order.name)
