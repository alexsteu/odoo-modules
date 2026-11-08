from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    require_po_number = fields.Boolean(
        string="Requires a PO number",
        help="Sales orders for this customer cannot be confirmed without a customer reference.",
    )
