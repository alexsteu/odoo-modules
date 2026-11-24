from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestRequireCustomerRef(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.partner"].create({
            "name": "Ville de Morges", "is_company": True, "require_po_number": True,
        })
        cls.contact = cls.env["res.partner"].create({"name": "Buyer", "parent_id": cls.company.id})
        cls.free_customer = cls.env["res.partner"].create({"name": "Small shop"})
        cls.product = cls.env["product.product"].create({"name": "Chair", "list_price": 50})

    def _quotation(self, partner, reference=False):
        return self.env["sale.order"].create({
            "partner_id": partner.id,
            "client_order_ref": reference,
            "order_line": [Command.create({"product_id": self.product.id, "product_uom_qty": 1})],
        })

    def test_order_without_reference_is_blocked(self):
        quotation = self._quotation(self.company)
        with self.assertRaises(UserError) as error:
            quotation.action_confirm()
        self.assertEqual(quotation.state, "draft")
        self.assertIn("Ville de Morges", str(error.exception))

    def test_order_with_reference_is_confirmed(self):
        quotation = self._quotation(self.company, "PO-2026-0042")
        quotation.action_confirm()
        self.assertEqual(quotation.state, "sale")

    def test_contact_of_the_company_is_concerned_too(self):
        quotation = self._quotation(self.contact)
        with self.assertRaises(UserError):
            quotation.action_confirm()

    def test_other_customers_are_not_concerned(self):
        quotation = self._quotation(self.free_customer)
        quotation.action_confirm()
        self.assertEqual(quotation.state, "sale")

    def test_reference_made_of_spaces_does_not_count(self):
        quotation = self._quotation(self.company, "   ")
        with self.assertRaises(UserError):
            quotation.action_confirm()

    def test_checkbox_is_on_the_contact_form(self):
        arch = self.env.ref("base.view_partner_form").get_combined_arch()
        self.assertIn('name="require_po_number"', arch)
