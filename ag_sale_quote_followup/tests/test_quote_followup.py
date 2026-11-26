from datetime import date, datetime

from freezegun import freeze_time

from odoo import Command
from odoo.modules.migration import load_script
from odoo.tests import TransactionCase, tagged

from odoo.addons.mail.tests.common import MockEmail

DAY0 = "2026-03-02 09:00:00"     # the quotation is sent that Monday morning


@tagged("post_install", "-at_install")
class TestQuoteFollowup(TransactionCase, MockEmail):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # rules added by other modules of the suite must not decide the result of these tests
        if "sale_minimum_amount" in cls.env.company._fields:
            cls.env.company.sale_minimum_amount = 0
        settings = {
            "quote_followup_enabled": True,
            "quote_followup_days": 5,
            "quote_followup_max": 2,
            "quote_followup_start_date": "2026-01-01",
        }
        cls.env.company.write({name: value for name, value in settings.items() if name in cls.env.company._fields})
        cls.customer = cls.env["res.partner"].create({
            "name": "Boulangerie Martin", "email": "martin@boulangerie.example", "lang": "en_US",
        })
        cls.product = cls.env["product.product"].create({"name": "Oven", "list_price": 1200})

    def _quotation(self, sent_on=DAY0, **values):
        order = self.env["sale.order"].create(dict({
            "partner_id": self.customer.id,
            "order_line": [Command.create({"product_id": self.product.id, "product_uom_qty": 1})],
        }, **values))
        if sent_on:
            with freeze_time(sent_on):
                order.action_quotation_sent()
        return order

    def _run(self, when):
        """Run the daily job at the given time and return the e-mails it sent."""
        with freeze_time(when), self.mock_mail_gateway():
            self.env["sale.order"]._cron_send_quote_followups()
            self.env.flush_all()
        return list(self._mails)

    def _to_customer(self, mails):
        return [mail for mail in mails if any("martin@boulangerie.example" in to for to in mail["email_to"])]

    # ------------------------------------------------------------------ main path
    def test_customer_gets_a_reminder_after_the_delay(self):
        order = self._quotation()
        self.assertFalse(self._run("2026-03-06 09:30:00"), "4 days: too early")
        self.assertEqual(order.followup_count, 0)

        mails = self._to_customer(self._run("2026-03-07 09:30:00"))
        self.assertEqual(len(mails), 1, "5 days after sending: one reminder to the customer")
        self.assertIn(order.name, mails[0]["subject"])
        self.assertIn("View the quotation", mails[0]["body"])
        self.assertIn("/my/orders/%s" % order.id, mails[0]["body"])
        self.assertEqual(order.followup_count, 1)
        self.assertEqual(order.followup_last_date, datetime(2026, 3, 7, 9, 30))
        self.assertEqual(order.state, "sent")

    def test_reminders_stop_at_the_maximum(self):
        order = self._quotation()
        self.assertEqual(len(self._to_customer(self._run("2026-03-07 10:00:00"))), 1)
        self.assertFalse(self._run("2026-03-11 10:00:00"), "only 4 days after the first reminder")
        self.assertEqual(len(self._to_customer(self._run("2026-03-12 10:00:00"))), 1)
        self.assertEqual(order.followup_count, 2)
        self.assertFalse(self._run("2026-04-20 10:00:00"), "maximum of 2 reached")
        self.assertEqual(order.followup_count, 2)

    def test_delay_counts_from_the_day_the_quotation_was_sent(self):
        """A quotation prepared a month ago and sent yesterday must not be chased today."""
        order = self._quotation(sent_on=False)
        order.date_order = datetime(2026, 2, 1, 8, 0)
        with freeze_time(DAY0):
            order.action_quotation_sent()
        self.assertFalse(self._run("2026-03-03 09:00:00"))
        self.assertEqual(order.followup_count, 0)
        self.assertEqual(len(self._to_customer(self._run("2026-03-07 09:00:00"))), 1)

    def test_next_reminder_date_is_visible_on_the_quotation(self):
        order = self._quotation()
        with freeze_time("2026-03-03 12:00:00"):
            order.invalidate_recordset()
            self.assertEqual(order.followup_next_date, date(2026, 3, 7))
        with freeze_time("2026-03-09 07:00:00"):
            order.invalidate_recordset()
            self.assertEqual(order.followup_next_date, date(2026, 3, 9), "already due: it leaves today, never a past date")
        order.followup_stop = True
        with freeze_time("2026-03-03 12:00:00"):
            order.invalidate_recordset()
            self.assertFalse(order.followup_next_date)

    # ------------------------------------------------------------------ who is never chased
    def test_quotation_not_sent_yet_is_ignored(self):
        self._quotation(sent_on=False)
        self.assertFalse(self._run("2026-03-20 09:00:00"))

    def test_confirmed_order_is_ignored(self):
        order = self._quotation()
        order.action_confirm()
        self.assertFalse(self._run("2026-03-20 09:00:00"))

    def test_stopped_quotation_is_ignored(self):
        self._quotation(followup_stop=True)
        self.assertFalse(self._run("2026-03-20 09:00:00"))

    def test_expired_quotation_is_ignored(self):
        self._quotation(validity_date="2026-03-05")
        self.assertFalse(self._run("2026-03-20 09:00:00"))

    def test_customer_without_email_is_ignored(self):
        self.customer.email = False
        order = self._quotation()
        self.assertFalse(self._run("2026-03-20 09:00:00"))
        self.assertEqual(order.followup_count, 0)

    def test_nothing_is_sent_when_the_option_is_off(self):
        self.env.company.quote_followup_enabled = False
        self._quotation()
        self.assertFalse(self._run("2026-03-20 09:00:00"))

    def test_old_quotations_are_not_chased_when_the_module_is_installed(self):
        """Installing the module must never e-mail every old quotation of the database."""
        self.env.company.quote_followup_start_date = "2026-03-10"
        old = self._quotation()                                   # sent on 2 March
        recent = self._quotation(sent_on="2026-03-11 09:00:00")
        mails = self._to_customer(self._run("2026-03-20 09:00:00"))
        self.assertEqual(len(mails), 1)
        self.assertIn(recent.name, mails[0]["subject"])
        self.assertEqual(old.followup_count, 0)

    def test_message_written_since_does_not_bring_an_old_quotation_back(self):
        """The start date looks at the day the quotation was sent, not at the last message."""
        self.env.company.quote_followup_start_date = "2026-03-10"
        old = self._quotation()                                   # sent on 2 March
        with freeze_time("2026-03-12 16:00:00"):
            old.message_post(
                body="Any news about our quotation?",
                message_type="comment", subtype_xmlid="mail.mt_comment",
            )
        self.assertFalse(old.followup_next_date)
        self.assertFalse(self._run("2026-03-25 09:00:00"))
        self.assertEqual(old.followup_count, 0)

    def test_empty_start_date_means_no_limit(self):
        self.env.company.quote_followup_start_date = False
        order = self._quotation(sent_on="2025-11-20 09:00:00", validity_date="2026-12-31")
        self.assertEqual(len(self._to_customer(self._run("2026-03-20 09:00:00"))), 1)
        self.assertEqual(order.followup_count, 1)

    def _sent_before_the_installation(self, quotation_date):
        """A quotation that was already in Quotation Sent when the module was installed."""
        order = self._quotation(date_order=quotation_date)
        order.followup_sent_date = False
        self.env.flush_all()
        return order

    def test_quotation_sent_before_the_installation_is_protected_by_the_start_date(self):
        self.env.company.quote_followup_start_date = "2026-03-10"
        order = self._sent_before_the_installation("2026-03-01 08:00:00")
        with freeze_time("2026-03-12 16:00:00"):
            order.message_post(
                body="Any news about our quotation?",
                message_type="comment", subtype_xmlid="mail.mt_comment",
            )
        self.assertFalse(self._run("2026-03-25 09:00:00"))

    def test_quotation_sent_before_the_installation_counts_from_its_date(self):
        """The day it was sent is not known: with no start date, the quotation date stands for it."""
        self.env.company.quote_followup_start_date = False
        self._sent_before_the_installation("2026-03-01 08:00:00")
        self.assertFalse(self._run("2026-03-05 09:00:00"), "4 days after the quotation date: too early")
        self.assertEqual(len(self._to_customer(self._run("2026-03-06 09:00:00"))), 1)

    # ------------------------------------------------------------------ upgrade from 1.0.x
    def _upgrade_script(self):
        return load_script(
            "ag_sale_quote_followup/migrations/1.1.0/post-migrate.py", "ag_followup_post_migrate")

    def test_upgrade_keeps_the_follow_ups_in_progress(self):
        """Upgrading from 1.0.x must not stop the follow-up of the quotations already sent."""
        order = self._quotation()                                   # sent on 2 March
        self.assertEqual(len(self._to_customer(self._run("2026-03-07 09:30:00"))), 1)
        # what the upgrade does to the new column: it takes its default, the day of the upgrade
        self.env.company.quote_followup_start_date = "2026-03-10"
        self.assertFalse(self._run("2026-03-12 09:30:00"), "without the script, the second reminder is lost")

        self._upgrade_script().migrate(self.env.cr, "17.0.1.0.1")
        self.env.invalidate_all()
        self.assertFalse(self.env.company.quote_followup_start_date, "empty: no limit, as in 1.0.x")
        self.assertEqual(len(self._to_customer(self._run("2026-03-12 09:30:00"))), 1)
        self.assertEqual(order.followup_count, 2)

    def test_upgrade_leaves_the_date_where_the_follow_up_was_off(self):
        """Nothing was in progress there: switching it on later must not chase every old quotation."""
        self.env.company.quote_followup_enabled = False
        self.env.company.quote_followup_start_date = "2026-03-10"   # the day of the upgrade
        old = self._quotation()                                     # sent on 2 March
        self.env.flush_all()
        self._upgrade_script().migrate(self.env.cr, "17.0.1.0.1")
        self.env.invalidate_all()
        self.assertEqual(self.env.company.quote_followup_start_date, date(2026, 3, 10))

        self.env.company.quote_followup_enabled = True
        self.assertFalse(self._run("2026-03-20 09:00:00"))
        self.assertEqual(old.followup_count, 0)

    def test_upgrade_counts_the_delay_from_the_quotation_date(self):
        """1.0.x did not record the day a quotation was sent: the script writes the quotation date."""
        order = self._sent_before_the_installation("2026-03-01 08:00:00")   # as version 1.0.x left it

        self._upgrade_script().migrate(self.env.cr, "17.0.1.0.1")
        self.env.invalidate_all()
        self.assertEqual(order.followup_sent_date, datetime(2026, 3, 1, 8, 0))
        self.assertFalse(self._run("2026-03-05 09:00:00"), "4 days after the quotation date: too early")
        self.assertEqual(len(self._to_customer(self._run("2026-03-06 09:00:00"))), 1)

    def test_upgrade_script_does_nothing_on_a_new_installation(self):
        self.env.company.quote_followup_start_date = "2026-03-10"
        self.env.flush_all()
        self._upgrade_script().migrate(self.env.cr, None)
        self.env.invalidate_all()
        self.assertEqual(self.env.company.quote_followup_start_date, date(2026, 3, 10))

    # ------------------------------------------------------------------ conversation with the customer
    def test_no_reminder_when_the_customer_has_answered(self):
        order = self._quotation()
        with freeze_time("2026-03-04 15:00:00"):
            order.message_post(
                body="Thanks, we discuss it on Friday and come back to you.",
                author_id=self.customer.id, message_type="email", subtype_xmlid="mail.mt_comment",
            )
        self.assertFalse(self._run("2026-03-20 09:00:00"))
        self.assertEqual(order.followup_count, 0)

    def test_message_from_the_salesperson_restarts_the_delay(self):
        order = self._quotation()
        with freeze_time("2026-03-06 16:00:00"):
            order.message_post(
                body="As discussed by phone, here is the updated delivery date.",
                message_type="comment", subtype_xmlid="mail.mt_comment",
            )
        self.assertFalse(self._run("2026-03-08 09:00:00"), "they were contacted 2 days ago")
        self.assertEqual(len(self._to_customer(self._run("2026-03-11 16:30:00"))), 1)

    def test_internal_note_does_not_restart_the_delay(self):
        order = self._quotation()
        with freeze_time("2026-03-06 16:00:00"):
            order.message_post(body="Call them next week", subtype_xmlid="mail.mt_note")
        self.assertEqual(len(self._to_customer(self._run("2026-03-07 09:30:00"))), 1)

    # ------------------------------------------------------------------ robustness and language
    def test_one_failure_does_not_block_the_other_quotations(self):
        broken = self._quotation()
        good = self._quotation()
        SaleOrder = type(self.env["sale.order"])
        original = SaleOrder.message_post_with_source

        def message_post_with_source(orders, *args, **kwargs):
            if orders == broken:
                raise ValueError("mail server refused the message")
            return original(orders, *args, **kwargs)

        self.patch(SaleOrder, "message_post_with_source", message_post_with_source)
        with self.assertLogs("odoo.addons.ag_sale_quote_followup.models.sale_order", level="ERROR"):
            mails = self._to_customer(self._run("2026-03-07 09:30:00"))
        self.assertEqual(len(mails), 1)
        self.assertEqual(good.followup_count, 1)
        self.assertEqual(broken.followup_count, 0)

    def test_greeting_names_a_person_but_not_a_company(self):
        """"Hello Boulangerie Martin SA," is not how a salesperson writes."""
        self._quotation()
        body = self._to_customer(self._run("2026-03-07 09:30:00"))[0]["body"]
        self.assertIn("Hello Boulangerie Martin,", body)
        self.customer.is_company = True
        body = self._to_customer(self._run("2026-03-12 09:30:00"))[0]["body"]
        self.assertIn("Hello,", body)
        self.assertNotIn("Hello Boulangerie Martin", body)

    def test_french_customer_gets_a_french_reminder(self):
        self.env["res.lang"]._activate_lang("fr_FR")
        self.env["ir.module.module"]._load_module_terms(["ag_sale_quote_followup"], ["fr_FR"], overwrite=True)
        self.customer.lang = "fr_FR"
        order = self._quotation()
        mails = self._to_customer(self._run("2026-03-07 09:30:00"))
        self.assertEqual(len(mails), 1)
        self.assertIn("votre devis %s" % order.name, mails[0]["subject"])
        self.assertIn("Voir le devis", mails[0]["body"])

    def test_settings_and_fields_are_in_the_screens(self):
        settings = self.env.ref("sale.res_config_settings_view_form").get_combined_arch()
        self.assertIn('name="quote_followup_days"', settings)
        self.assertIn('name="quote_followup_start_date"', settings)
        form = self.env.ref("sale.view_order_form").get_combined_arch()
        self.assertIn('name="followup_stop"', form)
        self.assertIn('name="followup_next_date"', form)
