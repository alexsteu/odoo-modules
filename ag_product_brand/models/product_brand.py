from odoo import fields, models


class ProductBrand(models.Model):
    _name = "product.brand"
    _description = "Product Brand"
    _order = "name"

    name = fields.Char(required=True, translate=True)
    logo = fields.Image(max_width=256, max_height=256)
    description = fields.Text(translate=True)
    active = fields.Boolean(default=True)
    product_ids = fields.One2many("product.template", "product_brand_id", string="Products")
    product_count = fields.Integer(compute="_compute_product_count")

    _sql_constraints = [("name_uniq", "unique(name)", "This brand already exists.")]

    def _compute_product_count(self):
        counts = dict(self.env["product.template"]._read_group(
            [("product_brand_id", "in", self.ids)], ["product_brand_id"], ["__count"]
        ))
        for brand in self:
            brand.product_count = counts.get(brand, 0)

    def action_view_products(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("sale.product_template_action")
        action["domain"] = [("product_brand_id", "=", self.id)]
        action["context"] = {"default_product_brand_id": self.id}
        return action
