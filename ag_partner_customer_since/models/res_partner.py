from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    customer_since = fields.Date(string="Customer since", compute="_compute_customer_since")

    def _compute_customer_since(self):
        """Date of the first confirmed sales order of the company or of any of its contacts.

        Read with sudo() and in one grouped query: the contact form is also opened by people who
        cannot read sales orders (accounting, project, purchase...) and an export reads hundreds
        of contacts at once.
        """
        commercial_by_partner = {partner: partner._origin.commercial_partner_id for partner in self}
        commercial_ids = list({commercial.id for commercial in commercial_by_partner.values() if commercial})
        first_order = {}
        if commercial_ids:
            groups = self.env["sale.order"].sudo()._read_group(
                [
                    ("partner_id", "child_of", commercial_ids),
                    ("state", "=", "sale"),
                    ("company_id", "in", self.env.companies.ids),
                ],
                ["partner_id"],
                ["date_order:min"],
            )
            for order_partner, first in groups:
                commercial_id = order_partner.commercial_partner_id.id
                if first and (commercial_id not in first_order or first < first_order[commercial_id]):
                    first_order[commercial_id] = first
        for partner in self:
            first = first_order.get(commercial_by_partner[partner].id)
            partner.customer_since = fields.Datetime.context_timestamp(partner, first).date() if first else False
