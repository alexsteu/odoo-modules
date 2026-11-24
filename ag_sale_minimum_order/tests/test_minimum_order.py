from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMinimumOrder(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Customer"})
        cls.product = cls.env["product.product"].create({"name": "Chair", "list_price": 50, "taxes_id": False})
        cls.env.company.sale_minimum_amount = 200

    def _quotation(self, quantity, **values):
        return self.env["sale.order"].create(dict({
            "partner_id": self.partner.id,
            "order_line": [Command.create({
                "product_id": self.product.id, "product_uom_qty": quantity, "price_unit": 50,
            })],
        }, **values))

    def test_order_below_the_minimum_is_blocked(self):
        quotation = self._quotation(3)
        with self.assertRaises(UserError) as error:
            quotation.action_confirm()
        self.assertEqual(quotation.state, "draft")
        self.assertIn(quotation.name, str(error.exception))

    def test_message_shows_both_amounts_with_the_currency(self):
        quotation = self._quotation(3)
        with self.assertRaises(UserError) as error:
            quotation.action_confirm()
        message = str(error.exception)
        symbol = self.env.company.currency_id.symbol
        self.assertIn(symbol, message)
        self.assertIn("150", message)
        self.assertIn("200", message)
        self.assertNotIn("200.0 ", message, "raw numbers like 200.0 look like a bug to the user")

    def test_order_at_the_minimum_is_confirmed(self):
        quotation = self._quotation(4)
        quotation.action_confirm()
        self.assertEqual(quotation.state, "sale")

    def test_zero_means_no_minimum(self):
        self.env.company.sale_minimum_amount = 0
        quotation = self._quotation(1)
        quotation.action_confirm()
        self.assertEqual(quotation.state, "sale")

    def test_order_in_another_currency_is_converted(self):
        company_currency = self.env.company.currency_id
        foreign = self.env["res.currency"].with_context(active_test=False).search(
            [("id", "!=", company_currency.id), ("name", "in", ("EUR", "USD", "CHF", "GBP"))], limit=1)
        foreign.active = True
        self.env["res.currency.rate"].search([("currency_id", "=", foreign.id)]).unlink()
        self.env["res.currency.rate"].create({
            "currency_id": foreign.id, "rate": 2.0, "name": "2020-01-01", "company_id": self.env.company.id,
        })
        pricelist = self.env["product.pricelist"].create({"name": "Foreign", "currency_id": foreign.id})
        # minimum 200 in company currency = 400 in the foreign currency
        low = self._quotation(6, pricelist_id=pricelist.id)       # 300 foreign = 150 company
        self.assertEqual(low.currency_id, foreign)
        with self.assertRaises(UserError):
            low.action_confirm()
        high = self._quotation(8, pricelist_id=pricelist.id)      # 400 foreign = 200 company
        high.action_confirm()
        self.assertEqual(high.state, "sale")

    def test_setting_is_in_the_sales_settings(self):
        arch = self.env.ref("sale.res_config_settings_view_form").get_combined_arch()
        self.assertIn('name="sale_minimum_amount"', arch)
