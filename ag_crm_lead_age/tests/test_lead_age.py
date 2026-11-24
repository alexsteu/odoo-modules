from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLeadAge(TransactionCase):

    def _lead(self, days_old):
        lead = self.env["crm.lead"].create({"name": "Fleet of vans", "type": "opportunity"})
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE crm_lead SET create_date = create_date - %s * interval '1 day' WHERE id = %s",
            [days_old, lead.id],
        )
        lead.invalidate_recordset()
        return lead

    def test_new_opportunity_is_zero_days_old(self):
        self.assertEqual(self._lead(0).age_days, 0)

    def test_age_is_the_number_of_days_since_creation(self):
        self.assertEqual(self._lead(12).age_days, 12)
        self.assertEqual(self._lead(45).age_days, 45)

    def test_column_is_in_the_opportunity_list(self):
        arch = self.env.ref("crm.crm_case_tree_view_oppor").get_combined_arch()
        self.assertIn('name="age_days"', arch)
