from psycopg2 import IntegrityError

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged, new_test_user
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestProductBrand(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.brand = cls.env["product.brand"].create({"name": "Bosch Pro"})
        cls.other_brand = cls.env["product.brand"].create({"name": "Makita"})
        cls.drill = cls.env["product.template"].create({
            "name": "Drill 18V", "list_price": 200, "product_brand_id": cls.brand.id,
        })
        cls.saw = cls.env["product.template"].create({
            "name": "Circular saw", "list_price": 300, "product_brand_id": cls.brand.id,
        })
        cls.env["product.template"].create({
            "name": "Sander", "list_price": 150, "product_brand_id": cls.other_brand.id,
        })
        cls.partner = cls.env["res.partner"].create({"name": "Customer"})

    def test_product_count(self):
        self.assertEqual(self.brand.product_count, 2)
        self.assertEqual(self.other_brand.product_count, 1)

    def test_button_opens_only_the_products_of_the_brand(self):
        action = self.brand.action_view_products()
        products = self.env["product.template"].search(action["domain"])
        self.assertEqual(products, self.drill | self.saw)
        self.assertEqual(action["context"]["default_product_brand_id"], self.brand.id)

    def test_brand_name_is_unique(self):
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"), self.env.cr.savepoint():
            self.env["product.brand"].create({"name": "Bosch Pro"})

    def test_deleting_a_brand_keeps_the_products(self):
        self.brand.unlink()
        self.assertTrue(self.drill.exists())
        self.assertFalse(self.drill.product_brand_id)

    def test_only_sales_managers_edit_brands(self):
        salesman = new_test_user(self.env, login="brand_salesman", groups="sales_team.group_sale_salesman")
        manager = new_test_user(self.env, login="brand_manager", groups="sales_team.group_sale_manager")
        self.assertEqual(self.brand.with_user(salesman).name, "Bosch Pro")
        with self.assertRaises(AccessError):
            self.env["product.brand"].with_user(salesman).create({"name": "Festool"})
        self.assertTrue(self.env["product.brand"].with_user(manager).create({"name": "Festool"}))

    def test_sales_analysis_groups_by_brand(self):
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "order_line": [
                Command.create({"product_id": self.drill.product_variant_id.id, "product_uom_qty": 2, "price_unit": 200}),
                Command.create({"product_id": self.saw.product_variant_id.id, "product_uom_qty": 1, "price_unit": 300}),
            ],
        })
        order.action_confirm()
        self.env.flush_all()
        rows = self.env["sale.report"]._read_group(
            [("order_reference", "=", "sale.order,%s" % order.id)] if "order_reference" in self.env["sale.report"]._fields
            else [("order_id", "=", order.id)],
            ["product_brand_id"], ["product_uom_qty:sum"],
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], self.brand)
        self.assertEqual(rows[0][1], 3)

    def test_brand_is_searchable_on_products(self):
        arch = self.env.ref("product.product_template_search_view").get_combined_arch()
        self.assertIn('name="product_brand_id"', arch)
        self.assertIn("groupby_brand", arch)
