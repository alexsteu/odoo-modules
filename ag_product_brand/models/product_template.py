from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    product_brand_id = fields.Many2one("product.brand", string="Brand", index=True, ondelete="set null")


class SaleReport(models.Model):
    _inherit = "sale.report"

    product_brand_id = fields.Many2one("product.brand", string="Brand", readonly=True)

    def _select_additional_fields(self):
        res = super()._select_additional_fields()
        res["product_brand_id"] = "t.product_brand_id"
        return res

    def _group_by_sale(self):
        return super()._group_by_sale() + ", t.product_brand_id"
