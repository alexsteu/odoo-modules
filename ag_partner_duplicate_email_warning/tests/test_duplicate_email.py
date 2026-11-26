from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDuplicateEmailWarning(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.existing = cls.env["res.partner"].create({
            "name": "Garage Rochat", "email": "contact@garage-rochat.example",
        })

    def _warning(self, email, record=None):
        partner = record or self.env["res.partner"].new({"name": "New", "email": email})
        if record:
            partner = self.env["res.partner"].new({"email": email}, origin=record)
        return partner._onchange_email_duplicate_warning()

    def test_warning_names_the_existing_contact(self):
        result = self._warning("contact@garage-rochat.example")
        self.assertTrue(result and result.get("warning"))
        self.assertIn("Garage Rochat", result["warning"]["message"])

    def test_case_and_spaces_do_not_matter(self):
        self.assertTrue(self._warning("  Contact@Garage-Rochat.example "))

    def test_no_warning_for_a_new_address(self):
        self.assertFalse(self._warning("someone.else@garage-rochat.example"))

    def test_no_warning_for_an_empty_address(self):
        self.assertFalse(self._warning(""))
        self.assertFalse(self._warning(False))

    def test_no_warning_against_itself(self):
        self.assertFalse(self._warning("contact@garage-rochat.example", record=self.existing))

    def test_underscore_is_not_a_wildcard(self):
        """john_doe@ must not be reported as a duplicate of johnxdoe@."""
        self.env["res.partner"].create({"name": "John X", "email": "johnxdoe@firm.example"})
        self.assertFalse(self._warning("john_doe@firm.example"))

    def test_address_written_with_a_name_is_recognised(self):
        self.assertTrue(self._warning('"Garage Rochat" <contact@garage-rochat.example>'))
