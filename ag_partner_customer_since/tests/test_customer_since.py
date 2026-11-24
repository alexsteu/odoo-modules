from datetime import datetime

from odoo import Command
from odoo.tests import TransactionCase, tagged, new_test_user


@tagged("post_install", "-at_install")
class TestCustomerSince(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.partner"].create({"name": "Menuiserie Favre", "is_company": True})
        cls.contact = cls.env["res.partner"].create({"name": "Luc Favre", "parent_id": cls.company.id})
        cls.product = cls.env["product.product"].create({"name": "Service", "list_price": 100})

    def _order(self, partner, date, confirm=True):
        order = self.env["sale.order"].create({
            "partner_id": partner.id,
            "order_line": [Command.create({"product_id": self.product.id, "product_uom_qty": 1})],
        })
        if confirm:
            order.action_confirm()
        order.date_order = date
        return order

    def test_prospect_has_no_date(self):
        self.assertFalse(self.company.customer_since)
        self._order(self.company, datetime(2024, 3, 5, 10, 0), confirm=False)
        self.company.invalidate_recordset()
        self.assertFalse(self.company.customer_since, "a quotation is not an order")

    def test_date_of_the_first_confirmed_order(self):
        self._order(self.company, datetime(2025, 6, 1, 10, 0))
        self._order(self.company, datetime(2024, 3, 5, 10, 0))
        self.company.invalidate_recordset()
        self.assertEqual(str(self.company.customer_since), "2024-03-05")

    def test_orders_of_the_contacts_count_for_the_company(self):
        self._order(self.contact, datetime(2023, 1, 9, 10, 0))
        self._order(self.company, datetime(2024, 3, 5, 10, 0))
        (self.company | self.contact).invalidate_recordset()
        self.assertEqual(str(self.company.customer_since), "2023-01-09")
        self.assertEqual(str(self.contact.customer_since), "2023-01-09")

    def test_user_without_sales_rights_can_open_the_contact(self):
        """A project or accounting user opens contacts too: the form must not crash."""
        self._order(self.company, datetime(2024, 3, 5, 10, 0))
        user = new_test_user(self.env, login="no_sales_rights", groups="base.group_user,base.group_partner_manager")
        self.company.invalidate_recordset()
        value = self.company.with_user(user).customer_since
        self.assertEqual(str(value), "2024-03-05")

    def test_many_contacts_read_with_few_queries(self):
        partners = self.company | self.contact
        for index in range(20):
            partners |= self.env["res.partner"].create({"name": "Customer %s" % index})
        self._order(self.company, datetime(2024, 3, 5, 10, 0))
        partners.invalidate_recordset()
        self.env.flush_all()
        start = self.env.cr.sql_log_count
        partners.mapped("customer_since")
        used = self.env.cr.sql_log_count - start
        self.assertLess(used, 8, "one query per contact is too slow on an export (%s used)" % used)

    def test_field_is_on_the_contact_form(self):
        arch = self.env.ref("base.view_partner_form").get_combined_arch()
        self.assertIn('name="customer_since"', arch)
