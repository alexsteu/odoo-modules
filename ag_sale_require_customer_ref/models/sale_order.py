from odoo import _, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def action_confirm(self):
        for order in self:
            partner = order.partner_id.commercial_partner_id
            if (partner.require_po_number or order.partner_id.require_po_number) and not order.client_order_ref:
                raise UserError(_(
                    "%s requires a PO number. Please fill in the Customer Reference of %s before confirming.",
                    partner.display_name, order.name,
                ))
        return super().action_confirm()
