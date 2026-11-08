from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    sale_minimum_amount = fields.Monetary(string="Minimum order amount (untaxed)", currency_field="currency_id")
