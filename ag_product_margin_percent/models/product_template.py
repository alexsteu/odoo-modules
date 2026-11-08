from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    margin_percent = fields.Float(string="Margin %", compute="_compute_margin_percent", digits=(16, 1))

    @api.depends("list_price", "standard_price")
    def _compute_margin_percent(self):
        for product in self:
            price = product.list_price
            product.margin_percent = ((price - product.standard_price) / price * 100) if price else 0.0
