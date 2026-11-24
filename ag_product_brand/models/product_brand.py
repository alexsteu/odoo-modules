from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


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

    @api.constrains("name")
    def _check_name_in_every_language(self):
        """The rule above compares a name together with all its translations: in a database
        with two languages, the same brand typed once in each language would be accepted.
        Compare the names one language at a time as well."""
        self.flush_model(["name"])
        self.env.cr.execute(
            """
            SELECT mine.id
              FROM product_brand mine
              JOIN LATERAL jsonb_each_text(mine.name) AS my_name ON TRUE
              JOIN product_brand other ON other.id != mine.id
              JOIN LATERAL jsonb_each_text(other.name) AS their_name ON their_name.value = my_name.value
             WHERE mine.id IN %s
             LIMIT 1
            """,
            [tuple(self.ids)],
        )
        if self.env.cr.fetchone():
            raise ValidationError(_("This brand already exists."))

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
