from datetime import date

from freezegun import freeze_time

from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.mail.tests.common import MockEmail


@tagged("post_install", "-at_install")
class TestOverdueReminder(AccountTestInvoicingCommon, MockEmail):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        settings = {
            "overdue_reminder_enabled": True,
            "overdue_reminder_first_days": 3,
            "overdue_reminder_days": 7,
            "overdue_reminder_max": 3,
            "overdue_reminder_start_date": "2026-01-01",
        }
        cls.env.company.write({name: value for name, value in settings.items() if name in cls.env.company._fields})
        cls.customer = cls.env["res.partner"].create({
            "name": "Garage Rochat", "email": "compta@garage-rochat.example", "lang": "en_US",
        })

    def _invoice(self, due="2026-03-10", move_type="out_invoice", post=True, partner=None):
        invoice = self.init_invoice(
            move_type, partner=partner or self.customer, invoice_date="2026-02-08", amounts=[1000.0])
        invoice.invoice_date_due = due
        if post:
            invoice.action_post()
        return invoice

    def _run(self, when):
        with freeze_time(when), self.mock_mail_gateway():
            self.env["account.move"]._cron_send_overdue_reminders()
            self.env.flush_all()
        return [mail for mail in self._mails
                if any("compta@garage-rochat.example" in to for to in mail["email_to"])]

    def _pay(self, invoice, amount):
        self.env["account.payment.register"].with_context(
            active_model="account.move", active_ids=invoice.ids,
        ).create({"amount": amount, "payment_date": "2026-03-01"})._create_payments()

    # ------------------------------------------------------------------ main path
    def test_first_reminder_leaves_a_few_days_for_the_bank_transfer(self):
        invoice = self._invoice()
        self.assertFalse(self._run("2026-03-11 08:00:00"), "1 day late: the transfer may be on its way")
        self.assertFalse(self._run("2026-03-12 08:00:00"))
        mails = self._run("2026-03-13 08:00:00")
        self.assertEqual(len(mails), 1, "3 days after the due date")
        self.assertIn(invoice.name, mails[0]["subject"])
        self.assertIn("1,000.00", mails[0]["body"])
        self.assertIn("View the invoice", mails[0]["body"])
        self.assertEqual(invoice.overdue_reminder_count, 1)
        self.assertEqual(invoice.overdue_reminder_last, date(2026, 3, 13))

    def test_following_reminders_and_maximum(self):
        invoice = self._invoice()
        self.assertEqual(len(self._run("2026-03-13 08:00:00")), 1)
        self.assertFalse(self._run("2026-03-19 08:00:00"), "6 days after the first one")
        self.assertEqual(len(self._run("2026-03-20 08:00:00")), 1)
        self.assertEqual(len(self._run("2026-03-27 08:00:00")), 1)
        self.assertEqual(invoice.overdue_reminder_count, 3)
        self.assertFalse(self._run("2026-05-01 08:00:00"), "maximum of 3 reached")

    def test_partially_paid_invoice_shows_what_is_left(self):
        invoice = self._invoice()
        self._pay(invoice, 400.0)
        mails = self._run("2026-03-13 08:00:00")
        self.assertEqual(len(mails), 1)
        self.assertIn("600.00", mails[0]["body"])

    def test_next_reminder_date_is_visible_on_the_invoice(self):
        invoice = self._invoice()
        with freeze_time("2026-03-05 08:00:00"):
            invoice.invalidate_recordset()
            self.assertEqual(invoice.overdue_reminder_next, date(2026, 3, 13))
        with freeze_time("2026-03-15 08:00:00"):
            invoice.invalidate_recordset()
            self.assertEqual(invoice.overdue_reminder_next, date(2026, 3, 15), "already due: it leaves today, never a past date")
        self._run("2026-03-13 08:00:00")
        with freeze_time("2026-03-14 08:00:00"):
            invoice.invalidate_recordset()
            self.assertEqual(invoice.overdue_reminder_next, date(2026, 3, 20))
        invoice.overdue_reminder_stop = True
        invoice.invalidate_recordset()
        self.assertFalse(invoice.overdue_reminder_next)

    # ------------------------------------------------------------------ who is never chased
    def test_paid_invoice_is_ignored(self):
        invoice = self._invoice()
        self._pay(invoice, 1000.0)
        self.assertFalse(self._run("2026-03-20 08:00:00"))

    def test_invoice_not_due_yet_is_ignored(self):
        self._invoice(due="2026-04-30")
        self.assertFalse(self._run("2026-03-20 08:00:00"))

    def test_draft_bill_and_credit_note_are_ignored(self):
        self._invoice(post=False)
        self._invoice(move_type="in_invoice")
        self._invoice(move_type="out_refund")
        self.assertFalse(self._run("2026-03-20 08:00:00"))

    def test_stopped_invoice_is_ignored(self):
        invoice = self._invoice()
        invoice.overdue_reminder_stop = True
        self.assertFalse(self._run("2026-03-20 08:00:00"))

    def test_customer_without_email_is_ignored(self):
        self.customer.email = False
        invoice = self._invoice()
        self.assertFalse(self._run("2026-03-20 08:00:00"))
        self.assertEqual(invoice.overdue_reminder_count, 0)

    def test_nothing_is_sent_when_the_option_is_off(self):
        self.env.company.overdue_reminder_enabled = False
        self._invoice()
        self.assertFalse(self._run("2026-03-20 08:00:00"))

    def test_old_invoices_are_not_chased_when_the_module_is_installed(self):
        """Installing the module must never e-mail every old unpaid invoice of the database."""
        self.env.company.overdue_reminder_start_date = "2026-03-01"
        old = self._invoice(due="2026-02-20")
        recent = self._invoice(due="2026-03-10")
        mails = self._run("2026-03-20 08:00:00")
        self.assertEqual(len(mails), 1)
        self.assertIn(recent.name, mails[0]["subject"])
        self.assertEqual(old.overdue_reminder_count, 0)

    # ------------------------------------------------------------------ robustness and language
    def test_one_failure_does_not_block_the_other_invoices(self):
        broken = self._invoice()
        good = self._invoice()
        Move = type(self.env["account.move"])
        original = Move.message_post_with_source

        def message_post_with_source(moves, *args, **kwargs):
            if moves == broken:
                raise ValueError("mail server refused the message")
            return original(moves, *args, **kwargs)

        self.patch(Move, "message_post_with_source", message_post_with_source)
        with self.assertLogs("odoo.addons.ag_invoice_overdue_reminder.models.account_move", level="ERROR"):
            mails = self._run("2026-03-13 08:00:00")
        self.assertEqual(len(mails), 1)
        self.assertEqual(good.overdue_reminder_count, 1)
        self.assertEqual(broken.overdue_reminder_count, 0)

    def test_greeting_names_a_person_but_not_a_company(self):
        self._invoice()
        body = self._run("2026-03-13 08:00:00")[0]["body"]
        self.assertIn("Hello Garage Rochat,", body)
        self.customer.is_company = True
        body = self._run("2026-03-20 08:00:00")[0]["body"]
        self.assertIn("Hello,", body)
        self.assertNotIn("Hello Garage Rochat", body)

    def test_french_customer_gets_a_french_reminder(self):
        self.env["res.lang"]._activate_lang("fr_FR")
        self.env["ir.module.module"]._load_module_terms(["ag_invoice_overdue_reminder"], ["fr_FR"], overwrite=True)
        self.customer.lang = "fr_FR"
        invoice = self._invoice()
        mails = self._run("2026-03-13 08:00:00")
        self.assertEqual(len(mails), 1)
        self.assertIn("rappel pour la facture %s" % invoice.name, mails[0]["subject"])
        self.assertIn("Voir la facture", mails[0]["body"])

    def test_settings_and_fields_are_in_the_screens(self):
        settings = self.env.ref("account.res_config_settings_view_form").get_combined_arch()
        self.assertIn('name="overdue_reminder_first_days"', settings)
        self.assertIn('name="overdue_reminder_start_date"', settings)
        form = self.env.ref("account.view_move_form").get_combined_arch()
        self.assertIn('name="overdue_reminder_stop"', form)
        self.assertIn('name="overdue_reminder_next"', form)
