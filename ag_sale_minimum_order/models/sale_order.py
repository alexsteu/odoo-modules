from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import formatLang


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def _ag_minimum_amount(self):
        """Minimum untaxed amount of the company, expressed in the currency of this order."""
        self.ensure_one()
        company = self.company_id
        minimum = company.sale_minimum_amount
        if minimum and self.currency_id and self.currency_id != company.currency_id:
            date = self.date_order or fields.Date.context_today(self)
            minimum = company.currency_id._convert(minimum, self.currency_id, company, date)
        return minimum

    def action_confirm(self):
        for order in self:
            minimum = order._ag_minimum_amount()
            if minimum and order.currency_id.compare_amounts(order.amount_untaxed, minimum) < 0:
                raise UserError(_(
                    "%(order)s cannot be confirmed: its untaxed amount is %(amount)s and the minimum order amount is %(minimum)s.",
                    order=order.name,
                    amount=formatLang(self.env, order.amount_untaxed, currency_obj=order.currency_id),
                    minimum=formatLang(self.env, minimum, currency_obj=order.currency_id),
                ))
        return super().action_confirm()
