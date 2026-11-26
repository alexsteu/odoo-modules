from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    vat_not_required = fields.Boolean(
        string="No Tax ID needed",
        help="Tick for a company that has no Tax ID / VAT number (small business below the VAT "
             "threshold, association...). Its invoices can then be posted without a number.",
    )
