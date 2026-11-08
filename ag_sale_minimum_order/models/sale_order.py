from odoo import _, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def action_confirm(self):
        for order in self:
            minimum = order.company_id.sale_minimum_amount
            if minimum and order.currency_id == order.company_id.currency_id and order.amount_untaxed < minimum:
                raise UserError(_(
                    "%s is below the minimum order amount (%s untaxed).",
                    order.name, minimum,
                ))
        return super().action_confirm()
