from odoo.tests import TransactionCase, tagged, new_test_user


@tagged("post_install", "-at_install")
class TestStaleOpportunityReminder(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.company.write({"stale_opportunity_enabled": True, "stale_opportunity_days": 10})
        cls.salesman = new_test_user(cls.env, login="stale_salesman", groups="sales_team.group_sale_salesman")
        cls.todo = cls.env.ref("mail.mail_activity_data_todo")

    def _opportunity(self, days_untouched, **values):
        lead = self.env["crm.lead"].create(dict({
            "name": "Roof for the Blanc family", "type": "opportunity", "user_id": self.salesman.id,
        }, **values))
        lead.activity_ids.unlink()
        self._age(lead, days_untouched)
        return lead

    def _age(self, lead, days):
        """Pretend nobody touched the opportunity (record and conversation) for `days` days."""
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE crm_lead SET write_date = now() at time zone 'utc' - %s * interval '1 day' WHERE id = %s",
            [days, lead.id])
        self.env.cr.execute(
            "UPDATE mail_message SET date = now() at time zone 'utc' - %s * interval '1 day' "
            "WHERE model = 'crm.lead' AND res_id = %s", [days, lead.id])
        self.env.invalidate_all()

    def _run(self):
        self.env["crm.lead"]._cron_remind_stale_opportunities()
        self.env.invalidate_all()

    def test_forgotten_opportunity_gets_a_todo_for_its_salesperson(self):
        lead = self._opportunity(15)
        self._run()
        activity = lead.activity_ids
        self.assertEqual(len(activity), 1)
        self.assertEqual(activity.user_id, self.salesman)
        self.assertEqual(activity.activity_type_id, self.todo)
        self.assertIn("10", activity.summary)

    def test_recent_opportunity_is_left_alone(self):
        lead = self._opportunity(3)
        self._run()
        self.assertFalse(lead.activity_ids)

    def test_no_duplicate_when_an_activity_is_already_planned(self):
        lead = self._opportunity(15)
        lead.activity_schedule("mail.mail_activity_data_call", user_id=self.salesman.id)
        self._age(lead, 15)
        self._run()
        self.assertEqual(len(lead.activity_ids), 1)

    def test_running_twice_creates_one_todo(self):
        lead = self._opportunity(15)
        self._run()
        self._run()
        self.assertEqual(len(lead.activity_ids), 1)

    def test_no_new_todo_the_day_after_the_salesperson_followed_up(self):
        """Marking the to-do as done is a follow-up: the next reminder comes after a new period of silence."""
        lead = self._opportunity(15)
        self._run()
        lead.activity_ids.action_feedback(feedback="Called, they decide next week")
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertFalse(lead.activity_ids)
        self._run()
        self.assertFalse(lead.activity_ids, "the salesperson has just followed up")
        self._age(lead, 11)
        self._run()
        self.assertEqual(len(lead.activity_ids), 1, "silent again for more than 10 days")

    def test_won_lost_and_unassigned_are_ignored(self):
        won_stage = self.env["crm.stage"].search([("is_won", "=", True)], limit=1)
        won = self._opportunity(15, stage_id=won_stage.id)
        lost = self._opportunity(15)
        lost.action_set_lost()
        unassigned = self._opportunity(15, user_id=False)
        raw_lead = self._opportunity(15, type="lead")
        for lead in (won, lost, unassigned, raw_lead):
            self._age(lead, 15)
        self._run()
        for lead in (won, lost, unassigned, raw_lead):
            self.assertFalse(lead.with_context(active_test=False).activity_ids, lead.name)

    def test_nothing_happens_when_the_option_is_off(self):
        self.env.company.stale_opportunity_enabled = False
        lead = self._opportunity(15)
        self._run()
        self.assertFalse(lead.activity_ids)

    def test_delay_is_configurable(self):
        self.env.company.stale_opportunity_days = 30
        lead = self._opportunity(15)
        self._run()
        self.assertFalse(lead.activity_ids)

    def test_setting_is_in_the_crm_settings(self):
        arch = self.env.ref("crm.res_config_settings_view_form").get_combined_arch()
        self.assertIn('name="stale_opportunity_days"', arch)
