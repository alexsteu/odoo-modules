from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestVatRequired(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_without_vat = cls.env["res.partner"].create({
            "name": "Atelier Durand SA", "is_company": True, "vat": False,
        })
        cls.contact_of_company = cls.env["res.partner"].create({
            "name": "Julie Durand", "parent_id": cls.company_without_vat.id,
        })
        cls.individual = cls.env["res.partner"].create({"name": "Marc Private", "is_company": False})

    def _invoice(self, partner, move_type="out_invoice"):
        return self.init_invoice(move_type, partner=partner, products=self.product_a)

    def test_company_without_vat_is_blocked(self):
        invoice = self._invoice(self.company_without_vat)
        with self.assertRaises(UserError) as error:
            invoice.action_post()
        self.assertIn("Atelier Durand SA", str(error.exception))
        self.assertEqual(invoice.state, "draft")

    def test_contact_of_a_company_without_vat_is_blocked(self):
        invoice = self._invoice(self.contact_of_company)
        with self.assertRaises(UserError):
            invoice.action_post()

    def test_credit_note_is_blocked_too(self):
        refund = self._invoice(self.company_without_vat, "out_refund")
        with self.assertRaises(UserError):
            refund.action_post()

    def test_company_with_vat_posts(self):
        self.company_without_vat.write({"country_id": self.env.ref("base.be").id, "vat": "BE0477472701"})
        invoice = self._invoice(self.company_without_vat)
        invoice.action_post()
        self.assertEqual(invoice.state, "posted")

    def test_individual_posts(self):
        invoice = self._invoice(self.individual)
        invoice.action_post()
        self.assertEqual(invoice.state, "posted")

    def test_vendor_bill_is_not_concerned(self):
        bill = self._invoice(self.company_without_vat, "in_invoice")
        bill.action_post()
        self.assertEqual(bill.state, "posted")

    def test_company_marked_as_not_subject_to_vat_posts(self):
        """Small companies below the VAT threshold have no number: the user must be able to say so."""
        self.assertIn("vat_not_required", self.env["res.partner"]._fields)
        self.company_without_vat.vat_not_required = True
        invoice = self._invoice(self.company_without_vat)
        invoice.action_post()
        self.assertEqual(invoice.state, "posted")

    def test_message_tells_how_to_fix(self):
        invoice = self._invoice(self.company_without_vat)
        with self.assertRaises(UserError) as error:
            invoice.action_post()
        self.assertIn("No Tax ID needed", str(error.exception))
