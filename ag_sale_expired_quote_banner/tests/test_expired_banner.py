from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestExpiredBanner(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # rules added by other modules of the suite must not decide the result of these tests
        if "sale_minimum_amount" in cls.env.company._fields:
            cls.env.company.sale_minimum_amount = 0
        cls.partner = cls.env["res.partner"].create({"name": "Customer"})

    def _quotation(self, validity_days):
        return self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "validity_date": fields.Date.today() + timedelta(days=validity_days),
        })

    def test_banner_is_in_the_quotation_form(self):
        arch = self.env.ref("sale.view_order_form").get_combined_arch()
        self.assertIn("This quotation has expired", arch)
        self.assertIn("not is_expired or state not in ('draft', 'sent')", arch)

    def test_expired_flag_follows_the_validity_date(self):
        self.assertTrue(self._quotation(-1).is_expired)
        self.assertFalse(self._quotation(0).is_expired, "still valid on the last day")
        self.assertFalse(self._quotation(5).is_expired)

    def test_confirmed_order_is_never_expired(self):
        order = self._quotation(-3)
        order.action_confirm()
        self.assertFalse(order.is_expired and order.state in ("draft", "sent"))
