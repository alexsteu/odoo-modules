import logging
import threading
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Messages a customer can see or write (internal notes and system notifications are not a contact)
CUSTOMER_MESSAGE_TYPES = ("comment", "email", "email_outgoing")


class SaleOrder(models.Model):
    _inherit = "sale.order"

    followup_count = fields.Integer(string="Follow-ups sent", default=0, copy=False, readonly=True)
    followup_last_date = fields.Datetime(string="Last follow-up", copy=False, readonly=True)
    followup_sent_date = fields.Datetime(
        string="Quotation sent on", copy=False, readonly=True,
        help="Set when the quotation becomes Quotation Sent. The follow-up delay starts here.",
    )
    followup_stop = fields.Boolean(
        string="No automatic follow-up",
        copy=False,
        help="Tick to never send automatic reminders for this quotation.",
    )
    followup_next_date = fields.Datetime(
        string="Next automatic follow-up",
        compute="_compute_followup_next_date",
        help="When the next reminder will be e-mailed to the customer. Empty when none is planned: "
             "quotation not sent, follow-up stopped, maximum reached, quotation expired, customer "
             "without e-mail, or customer who already answered.",
    )

    # ------------------------------------------------------------------ sent date
    def write(self, vals):
        if vals.get("state") == "sent":
            newly_sent = self.filtered(lambda order: order.state != "sent")
            if newly_sent:
                # a quotation that is sent (again) starts a fresh follow-up cycle
                super(SaleOrder, newly_sent).write({
                    "followup_sent_date": fields.Datetime.now(),
                    "followup_count": 0,
                    "followup_last_date": False,
                })
        return super().write(vals)

    # ------------------------------------------------------------------ when is the next reminder due?
    def _followup_last_exchange(self):
        """{order id: (date, from_customer)} of the last message exchanged with the customer."""
        result = {}
        order_ids = self._origin.ids
        if not order_ids:
            return result
        messages = self.env["mail.message"].sudo().search([
            ("model", "=", "sale.order"),
            ("res_id", "in", order_ids),
            ("message_type", "in", CUSTOMER_MESSAGE_TYPES),
            ("subtype_id.internal", "=", False),
        ], order="date desc, id desc")
        staff = {}
        for message in messages:
            if message.res_id in result:
                continue
            author = message.author_id
            if author and author.id not in staff:
                users = author.with_context(active_test=False).user_ids
                staff[author.id] = any(not user.share for user in users)
            result[message.res_id] = (message.date, not (author and staff[author.id]))
        return result

    def _followup_next_dates(self):
        """{order id: datetime of its next automatic follow-up}, only for quotations that will get one."""
        result = {}
        today = fields.Date.context_today(self)
        candidates = self.filtered(
            lambda order: order.state == "sent" and not order.followup_stop and order.partner_id.email
        )
        exchanges = candidates._followup_last_exchange()
        for order in candidates:
            company = order.company_id
            if not company.quote_followup_enabled or order.followup_count >= company.quote_followup_max:
                continue
            if order.validity_date and order.validity_date < today:
                continue
            dates = [date for date in (order.followup_sent_date, order.followup_last_date) if date]
            last_date, from_customer = exchanges.get(order._origin.id, (False, False))
            if last_date:
                if from_customer and (not dates or last_date >= max(dates)):
                    continue        # the customer answered: it is the salesperson's turn
                dates.append(last_date)
            if not dates:
                continue            # sent before the module was installed and nothing exchanged since
            reference = max(dates)
            start = company.quote_followup_start_date
            if start and fields.Datetime.context_timestamp(order, reference).date() < start:
                continue            # old quotations are never chased by surprise
            result[order.id] = reference + timedelta(days=max(company.quote_followup_days, 1))
        return result

    @api.depends("state", "followup_stop", "followup_count", "followup_last_date", "followup_sent_date",
                 "validity_date", "partner_id")
    def _compute_followup_next_date(self):
        next_dates = self._followup_next_dates()
        for order in self:
            order.followup_next_date = next_dates.get(order.id, False)

    # ------------------------------------------------------------------ daily job
    @api.model
    def _cron_send_quote_followups(self):
        template = self.env.ref(
            "ag_sale_quote_followup.mail_template_quote_followup", raise_if_not_found=False
        )
        if not template:
            return
        now = fields.Datetime.now()
        # one commit per e-mail: a later failure never sends the same reminder twice
        auto_commit = not getattr(threading.current_thread(), "testing", False)
        companies = self.env["res.company"].search([("quote_followup_enabled", "=", True)])
        orders = self.search([
            ("company_id", "in", companies.ids),
            ("state", "=", "sent"),
            ("followup_stop", "=", False),
            ("partner_id.email", "!=", False),
        ])
        next_dates = orders._followup_next_dates()
        for order in orders:
            due = next_dates.get(order.id)
            if not due or due > now:
                continue
            try:
                with self.env.cr.savepoint():
                    order.with_context(mark_so_as_sent=False).message_post_with_source(
                        template, subtype_xmlid="mail.mt_comment"
                    )
                    order.write({
                        "followup_count": order.followup_count + 1,
                        "followup_last_date": now,
                    })
            except Exception:
                _logger.exception("Quotation follow-up failed for %s", order.name)
                continue
            if auto_commit:
                self.env.cr.commit()
