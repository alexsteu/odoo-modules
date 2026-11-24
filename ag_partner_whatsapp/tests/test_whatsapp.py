from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestWhatsappLink(TransactionCase):

    def _partner(self, **values):
        values.setdefault("name", "Test contact")
        return self.env["res.partner"].create(values)

    def test_international_number(self):
        partner = self._partner(phone="+41 76 488 27 10")
        self.assertEqual(partner.whatsapp_url, "https://wa.me/41764882710")

    def test_number_starting_with_double_zero(self):
        partner = self._partner(phone="0041 76 488 27 10")
        self.assertEqual(partner.whatsapp_url, "https://wa.me/41764882710")

    def test_mobile_is_preferred_to_phone(self):
        partner = self._partner(phone="+41 21 555 00 00", mobile="+33 6 12 34 56 78")
        self.assertEqual(partner.whatsapp_url, "https://wa.me/33612345678")

    def test_national_number_uses_the_country_of_the_contact(self):
        """Most companies type numbers the national way: 076 488 27 10."""
        partner = self._partner(phone="076 488 27 10", country_id=self.env.ref("base.ch").id)
        self.assertEqual(partner.whatsapp_url, "https://wa.me/41764882710")
        french = self._partner(mobile="06 12 34 56 78", country_id=self.env.ref("base.fr").id)
        self.assertEqual(french.whatsapp_url, "https://wa.me/33612345678")

    def test_national_number_without_country_uses_the_company_country(self):
        self.env.company.country_id = self.env.ref("base.be")
        partner = self._partner(mobile="0470 12 34 56", country_id=False)
        self.assertEqual(partner.whatsapp_url, "https://wa.me/32470123456")

    def test_no_link_without_a_usable_number(self):
        self.assertFalse(self._partner().whatsapp_url)
        self.assertFalse(self._partner(phone="ask reception").whatsapp_url)
        self.assertFalse(self._partner(phone="12").whatsapp_url)

    def test_link_is_on_the_contact_form(self):
        arch = self.env.ref("base.view_partner_form").get_combined_arch()
        self.assertIn('name="whatsapp_url"', arch)
