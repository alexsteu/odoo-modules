from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMarginPercent(TransactionCase):

    def _product(self, price, cost):
        return self.env["product.template"].create({
            "name": "Product", "list_price": price, "standard_price": cost,
        })

    def test_margin_on_the_sales_price(self):
        self.assertAlmostEqual(self._product(100, 60).margin_percent, 40.0)
        self.assertAlmostEqual(self._product(80, 20).margin_percent, 75.0)

    def test_product_sold_at_a_loss_is_negative(self):
        self.assertAlmostEqual(self._product(50, 75).margin_percent, -50.0)

    def test_free_product_does_not_crash(self):
        self.assertEqual(self._product(0, 10).margin_percent, 0.0)

    def test_margin_follows_a_price_change(self):
        product = self._product(100, 60)
        product.list_price = 120
        self.assertAlmostEqual(product.margin_percent, 50.0)

    def test_column_is_in_the_product_list(self):
        arch = self.env.ref("product.product_template_tree_view").get_combined_arch()
        self.assertIn('name="margin_percent"', arch)
