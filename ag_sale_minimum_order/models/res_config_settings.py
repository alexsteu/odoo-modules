from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    company_currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", string="Company Currency", readonly=True
    )
    sale_minimum_amount = fields.Monetary(
        related="company_id.sale_minimum_amount", readonly=False, currency_field="company_currency_id"
    )
