import base64
import json
from unittest.mock import patch

import requests

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

POST = "odoo.addons.ag_ai_vendor_bill.models.account_move.requests.post"
PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF"


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status
        self.text = json.dumps(payload)

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("%s error" % self.status_code, response=self)


def anthropic_answer(data, stop_reason="end_turn"):
    return FakeResponse({
        "type": "message", "role": "assistant", "stop_reason": stop_reason,
        "content": [{"type": "thinking", "thinking": "", "signature": "x"},
                    {"type": "text", "text": data if isinstance(data, str) else json.dumps(data)}],
    })


def openai_answer(data):
    return FakeResponse({"choices": [{"message": {"role": "assistant", "content": json.dumps(data)}}]})


@tagged("post_install", "-at_install")
class TestAiVendorBill(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        icp = cls.env["ir.config_parameter"].sudo()
        for name, value in (("ag_ai_bill.provider", "anthropic"), ("ag_ai_bill.api_key", "test-key"),
                            ("ag_ai_bill.model", False), ("ag_ai_quote.api_key", False)):
            icp.set_param(name, value)
        cls.tax_20 = cls.env["account.tax"].create({
            "name": "Purchase 20%", "amount": 20, "amount_type": "percent", "type_tax_use": "purchase",
            "company_id": cls.env.company.id,
        })
        cls.vendor = cls.env["res.partner"].create({
            "name": "Papeterie du Lac", "is_company": True,
            "country_id": cls.env.ref("base.be").id, "vat": "BE0477472701",
        })

    def _bill(self, mimetype="application/pdf", content=PDF, name="invoice.pdf", attach=True):
        bill = self.env["account.move"].create({"move_type": "in_invoice"})
        if attach:
            self.env["ir.attachment"].create({
                "name": name, "res_model": "account.move", "res_id": bill.id,
                "datas": base64.b64encode(content), "mimetype": mimetype,
            })
        return bill

    def _answer(self, **overrides):
        data = {
            "vendor": {"name": "PAPETERIE DU LAC SA", "vat": "BE 0477.472.701", "email": None,
                       "street": None, "zip": None, "city": None},
            "invoice_number": "F-2026-0815", "invoice_date": "2026-03-02", "due_date": "2026-04-01",
            "currency": self.env.company.currency_id.name,
            "lines": [
                {"description": "Paper A4 80g", "quantity": 10, "unit_price": 4.5, "tax_percent": 20},
                {"description": "Delivery", "quantity": 1, "unit_price": 15, "tax_percent": 20},
            ],
            "total_untaxed": 60.0, "total": 72.0,
        }
        data.update(overrides)
        return data

    def _note(self, bill):
        """Body of the note the reader leaves in the chatter of the bill.

        The note is not always the last message of the bill: when the tracking of fields is on
        (as in the test class of Odoo 17), the message that tracks the fields changed by the
        reader is written after the note.
        """
        notes = bill.message_ids.filtered(lambda message: "filled by AI" in str(message.body))
        self.assertEqual(len(notes), 1, "one note for one reading")
        return str(notes.body)

    # ------------------------------------------------------------------ main path
    def test_pdf_fills_the_draft_bill(self):
        bill = self._bill()
        with patch(POST, return_value=anthropic_answer(self._answer())) as post:
            bill.action_ag_ai_read_bill()
        self.assertEqual(bill.partner_id, self.vendor, "vendor found by its VAT number, whatever the spacing")
        self.assertEqual(bill.ref, "F-2026-0815")
        self.assertEqual(str(bill.invoice_date), "2026-03-02")
        self.assertEqual(str(bill.invoice_date_due), "2026-04-01")
        self.assertEqual(bill.invoice_line_ids.mapped("name"), ["Paper A4 80g", "Delivery"])
        self.assertEqual(bill.invoice_line_ids.mapped("quantity"), [10, 1])
        self.assertEqual(bill.invoice_line_ids.mapped("tax_ids"), self.tax_20)
        self.assertAlmostEqual(bill.amount_untaxed, 60.0)
        self.assertAlmostEqual(bill.amount_total, 72.0)
        self.assertEqual(bill.state, "draft", "the bill always stays in draft")
        self.assertTrue(bill.ag_ai_read)
        # what was sent: the PDF as a document block placed before the instructions
        request = post.call_args
        self.assertEqual(request.args[0], "https://api.anthropic.com/v1/messages")
        self.assertEqual(request.kwargs["headers"]["x-api-key"], "test-key")
        content = request.kwargs["json"]["messages"][0]["content"]
        self.assertEqual(content[0]["type"], "document")
        self.assertEqual(content[0]["source"]["media_type"], "application/pdf")
        self.assertEqual(base64.b64decode(content[0]["source"]["data"]), PDF)
        self.assertEqual(content[1]["type"], "text")
        self.assertEqual(request.kwargs["json"]["model"], "claude-sonnet-5-5")

    def test_photo_is_sent_as_an_image(self):
        bill = self._bill(mimetype="image/jpeg", content=b"\xff\xd8\xff\xe0fakejpeg", name="photo.jpg")
        with patch(POST, return_value=anthropic_answer(self._answer())) as post:
            bill.action_ag_ai_read_bill()
        self.assertEqual(post.call_args.kwargs["json"]["messages"][0]["content"][0]["type"], "image")
        self.assertEqual(len(bill.invoice_line_ids), 2)

    def test_chatgpt_provider(self):
        self.env["ir.config_parameter"].sudo().set_param("ag_ai_bill.provider", "openai")
        bill = self._bill()
        with patch(POST, return_value=openai_answer(self._answer())) as post:
            bill.action_ag_ai_read_bill()
        self.assertEqual(post.call_args.args[0], "https://api.openai.com/v1/chat/completions")
        self.assertEqual(len(bill.invoice_line_ids), 2)

    def test_total_mismatch_is_reported_in_the_chatter(self):
        bill = self._bill()
        with patch(POST, return_value=anthropic_answer(self._answer(total=75.6))):
            bill.action_ag_ai_read_bill()
        note = self._note(bill)
        self.assertIn("75.6", note)
        self.assertIn("72", note)

    def test_unknown_vendor_is_created(self):
        answer = self._answer(vendor={"name": "Imprimerie Nouvelle Sàrl", "vat": None, "email": "info@imprimerie.example",
                                      "street": "Rue du Lac 4", "zip": "1003", "city": "Lausanne"})
        bill = self._bill()
        with patch(POST, return_value=anthropic_answer(answer)):
            bill.action_ag_ai_read_bill()
        self.assertEqual(bill.partner_id.name, "Imprimerie Nouvelle Sàrl")
        self.assertTrue(bill.partner_id.is_company)
        self.assertEqual(bill.partner_id.city, "Lausanne")

    def test_misread_vat_number_does_not_block_the_bill(self):
        """A VAT number the AI misread fails Odoo's validation: the vendor is created without it."""
        answer = self._answer(vendor={"name": "Fournitures Dupont", "vat": "BE0000000000", "email": None,
                                      "street": None, "zip": None, "city": None})
        bill = self._bill()
        with patch(POST, return_value=anthropic_answer(answer)):
            bill.action_ag_ai_read_bill()
        self.assertEqual(bill.partner_id.name, "Fournitures Dupont")
        self.assertEqual(len(bill.invoice_line_ids), 2)

    def test_vendor_already_chosen_is_kept(self):
        other = self.env["res.partner"].create({"name": "Chosen by the accountant"})
        bill = self._bill()
        bill.partner_id = other
        with patch(POST, return_value=anthropic_answer(self._answer())):
            bill.action_ag_ai_read_bill()
        self.assertEqual(bill.partner_id, other)

    def test_unknown_tax_rate_leaves_the_line_without_tax(self):
        answer = self._answer(lines=[{"description": "Book", "quantity": 1, "unit_price": 30, "tax_percent": 3.7}], total=31.11)
        bill = self._bill()
        with patch(POST, return_value=anthropic_answer(answer)):
            bill.action_ag_ai_read_bill()
        self.assertFalse(bill.invoice_line_ids.tax_ids)

    def test_vendor_found_whatever_the_way_its_tax_id_is_printed(self):
        """Swiss numbers end with TVA, MWST or IVA depending on the language of the document."""
        swiss = self.env["res.partner"].create({
            "name": "Elektro Meier", "is_company": True, "country_id": self.env.ref("base.ch").id,
            "vat": "CHE-123.456.788 MWST",
        })
        answer = self._answer(vendor={"name": "Meier Elektro-Installationen", "vat": "CHE-123.456.788 TVA", "email": None,
                                      "street": None, "zip": None, "city": None, "country": "CH"})
        bill = self._bill()
        with patch(POST, return_value=anthropic_answer(answer)):
            bill.action_ag_ai_read_bill()
        self.assertEqual(bill.partner_id, swiss)
        # number printed without the country letters
        answer = self._answer(vendor={"name": "Lac Papeterie", "vat": "0477.472.701", "email": None,
                                      "street": None, "zip": None, "city": None})
        bill = self._bill()
        with patch(POST, return_value=anthropic_answer(answer)):
            bill.action_ag_ai_read_bill()
        self.assertEqual(bill.partner_id, self.vendor)

    def test_vendor_written_without_its_legal_form_is_not_created_twice(self):
        answer = self._answer(vendor={"name": "Papeterie du Lac S.A.", "vat": None, "email": None,
                                      "street": None, "zip": None, "city": None})
        bill = self._bill()
        with patch(POST, return_value=anthropic_answer(answer)):
            bill.action_ag_ai_read_bill()
        self.assertEqual(bill.partner_id, self.vendor, "Papeterie du Lac and Papeterie du Lac S.A. are the same vendor")

    def test_two_legal_forms_are_two_vendors(self):
        sarl = self.env["res.partner"].create({"name": "Dupont Sàrl", "is_company": True})
        answer = self._answer(vendor={"name": "Dupont SA", "vat": None, "email": None,
                                      "street": None, "zip": None, "city": None})
        bill = self._bill()
        with patch(POST, return_value=anthropic_answer(answer)):
            bill.action_ag_ai_read_bill()
        self.assertNotEqual(bill.partner_id, sarl)
        self.assertEqual(bill.partner_id.name, "Dupont SA")

    def test_new_vendor_gets_its_country(self):
        answer = self._answer(vendor={"name": "Schreinerei Huber", "vat": None, "email": None,
                                      "street": "Bahnhofstrasse 1", "zip": "8001", "city": "Zürich", "country": "ch"})
        bill = self._bill()
        with patch(POST, return_value=anthropic_answer(answer)):
            bill.action_ag_ai_read_bill()
        self.assertEqual(bill.partner_id.country_id, self.env.ref("base.ch"))

    def test_default_purchase_tax_is_preferred_among_taxes_with_the_same_rate(self):
        other_20 = self.tax_20.copy({"name": "Purchase 20% (services)", "sequence": 0})
        self.env.company.account_purchase_tax_id = self.tax_20
        bill = self._bill()
        with patch(POST, return_value=anthropic_answer(self._answer())):
            bill.action_ag_ai_read_bill()
        self.assertEqual(bill.invoice_line_ids.mapped("tax_ids"), self.tax_20)
        self.assertNotIn(other_20, bill.invoice_line_ids.mapped("tax_ids"))

    def test_inactive_currency_is_reported_and_not_switched_on(self):
        currency = self.env["res.currency"].with_context(active_test=False).search(
            [("active", "=", False), ("name", "!=", self.env.company.currency_id.name)], limit=1)
        if not currency:
            self.skipTest("every currency is active in this database")
        bill = self._bill()
        with patch(POST, return_value=anthropic_answer(self._answer(currency=currency.name))):
            bill.action_ag_ai_read_bill()
        self.assertFalse(currency.active, "a currency is never switched on behind the back of the accountant")
        self.assertEqual(bill.currency_id, self.env.company.currency_id)
        self.assertIn(currency.name, self._note(bill))

    def test_empty_document_is_reported(self):
        bill = self._bill()
        with patch(POST, return_value=anthropic_answer(self._answer(lines=[], total=None))):
            bill.action_ag_ai_read_bill()
        self.assertFalse(bill.invoice_line_ids)
        self.assertIn("No line", self._note(bill))

    # ------------------------------------------------------------------ several bills, errors
    def test_several_bills_one_failure_does_not_lose_the_others(self):
        good, no_file, unreadable = self._bill(), self._bill(attach=False), self._bill()
        answers = [anthropic_answer(self._answer()), anthropic_answer("I cannot read this document.")]
        with patch(POST, side_effect=answers):
            result = (good | no_file | unreadable).action_ag_ai_read_bill()
        self.assertEqual(len(good.invoice_line_ids), 2)
        self.assertFalse(no_file.invoice_line_ids)
        self.assertEqual(result["tag"], "display_notification")
        self.assertEqual(result["params"]["type"], "warning")
        self.assertIn("1", result["params"]["message"])

    def test_several_bills_service_error_keeps_the_bills_already_read(self):
        first, second = self._bill(), self._bill()
        down = FakeResponse({"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}, 529)
        with patch(POST, side_effect=[anthropic_answer(self._answer()), down]):
            result = (first | second).action_ag_ai_read_bill()
        self.assertEqual(len(first.invoice_line_ids), 2, "the first bill was read and paid for: keep it")
        self.assertFalse(second.invoice_line_ids)
        self.assertEqual(result["params"]["type"], "warning")

    def test_many_bills_stop_before_the_time_limit_of_odoo(self):
        """Odoo stops a request after two minutes: the action stops by itself and says what is left."""
        from odoo.addons.ag_ai_vendor_bill.models import account_move as module

        class Clock:
            now = 0.0

            def monotonic(self):
                return self.now

        clock = Clock()
        self.patch(module, "time", clock)

        def slow_answer(*args, **kwargs):
            clock.now += 30  # each reading takes 30 seconds
            return anthropic_answer(self._answer())

        bills = self._bill() | self._bill() | self._bill() | self._bill()
        with patch(POST, side_effect=slow_answer) as post:
            result = bills.action_ag_ai_read_bill()
        self.assertEqual(post.call_count, 2, "no new bill is started after 45 seconds")
        self.assertEqual(len(bills.filtered("ag_ai_read")), 2)
        self.assertIn("2 bill(s) not started", result["params"]["message"])
        self.assertEqual(post.call_args.kwargs["timeout"], module.BATCH_CALL_TIMEOUT)

    def test_refused_key_stops_at_the_first_bill(self):
        refused = FakeResponse({"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}, 401)
        with patch(POST, return_value=refused) as post, self.assertRaises(UserError):
            (self._bill() | self._bill() | self._bill()).action_ag_ai_read_bill()
        self.assertEqual(post.call_count, 1, "the same key would be refused for every bill")

    def test_refusal_and_cut_answers_are_explained(self):
        bill = self._bill()
        with patch(POST, return_value=anthropic_answer("", stop_reason="refusal")):
            result = bill.action_ag_ai_read_bill()
        self.assertIn("declined", result["params"]["message"])
        with patch(POST, return_value=anthropic_answer('{"vendor": {"name": "Pap', stop_reason="max_tokens")):
            result = bill.action_ag_ai_read_bill()
        self.assertIn("too long", result["params"]["message"])
        self.assertFalse(bill.ag_ai_read)

    def test_filter_of_bills_to_check_exists(self):
        search = self.env.ref("account.view_account_invoice_filter").get_combined_arch()
        self.assertIn("ag_ai_to_check", search)

    def test_single_bill_without_attachment_says_what_to_do(self):
        bill = self._bill(attach=False)
        with patch(POST) as post:
            result = bill.action_ag_ai_read_bill()
        post.assert_not_called()
        self.assertIn("no PDF or image", result["params"]["message"])

    def test_refused_key_is_explained_without_technical_noise(self):
        bill = self._bill()
        refused = FakeResponse({"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}, 401)
        with patch(POST, return_value=refused), self.assertRaises(UserError) as error:
            bill.action_ag_ai_read_bill()
        self.assertIn("API key", str(error.exception))
        self.assertNotIn("{", str(error.exception))

    def test_missing_key_explains_where_to_set_it(self):
        self.env["ir.config_parameter"].sudo().set_param("ag_ai_bill.api_key", False)
        bill = self._bill()
        with patch(POST) as post, self.assertRaises(UserError) as error:
            bill.action_ag_ai_read_bill()
        post.assert_not_called()
        self.assertIn("Settings", str(error.exception))

    def test_posted_bills_and_customer_invoices_are_refused(self):
        invoice = self.init_invoice("out_invoice", partner=self.partner_a, products=self.product_a)
        with self.assertRaises(UserError):
            invoice.action_ag_ai_read_bill()

    def test_button_and_settings_are_in_the_screens(self):
        form = self.env.ref("account.view_move_form").get_combined_arch()
        self.assertIn("action_ag_ai_read_bill", form)
        settings = self.env.ref("account.res_config_settings_view_form").get_combined_arch()
        self.assertIn('name="ag_ai_bill_api_key"', settings)
