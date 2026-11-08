from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    customer_since = fields.Date(string="Customer since", compute="_compute_customer_since")

    def _compute_customer_since(self):
        for partner in self:
            commercial = partner.commercial_partner_id
            first = self.env["sale.order"].search([
                ("partner_id", "child_of", commercial.id),
                ("state", "=", "sale"),
            ], order="date_order asc", limit=1) if commercial.id else False
            partner.customer_since = first.date_order.date() if first else False
