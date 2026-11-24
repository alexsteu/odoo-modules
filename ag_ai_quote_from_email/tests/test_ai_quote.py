import json
from unittest.mock import patch

import requests

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

POST = "odoo.addons.ag_ai_quote_from_email.models.sale_order.requests.post"

EMAIL = """Hello,
We would need 20 office chairs and 4 meeting tables for our new office in Lausanne,
plus a red sofa if you have one. Delivery before 15 December if possible.
Best regards, Nadia Keller - Keller Fiduciaire SA - nadia@keller-fiduciaire.example"""


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status
        self.text = json.dumps(payload)

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("%s error" % self.status_code, response=self)


def anthropic_answer(data, stop_reason="end_turn", prefix=""):
    return FakeResponse({
        "type": "message", "role": "assistant", "stop_reason": stop_reason,
        "content": [
            {"type": "thinking", "thinking": "", "signature": "x"},
            {"type": "text", "text": prefix + (data if isinstance(data, str) else json.dumps(data))},
        ],
    })


def openai_answer(data):
    return FakeResponse({"choices": [{"message": {"role": "assistant", "content": json.dumps(data)}}]})


@tagged("post_install", "-at_install")
class TestAiQuote(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        icp = cls.env["ir.config_parameter"].sudo()
        icp.set_param("ag_ai_quote.provider", "anthropic")
        icp.set_param("ag_ai_quote.api_key", "test-key")
        icp.set_param("ag_ai_quote.model", False)
        cls.chair = cls.env["product.product"].create({"name": "Office chair", "default_code": "CH-01", "list_price": 120})
        cls.table = cls.env["product.product"].create({"name": "Meeting table", "default_code": "TB-01", "list_price": 480})
        cls.customer = cls.env["res.partner"].create({
            "name": "Keller Fiduciaire SA", "is_company": True, "email": "nadia@keller-fiduciaire.example",
        })

    def _answer(self, **overrides):
        data = {
            "customer": {"name": "Nadia Keller", "company": "Keller Fiduciaire SA",
                         "email": "nadia@keller-fiduciaire.example", "phone": None},
            "lines": [
                {"product_id": self.chair.id, "description": "office chairs", "quantity": 20},
                {"product_id": self.table.id, "description": "meeting tables", "quantity": 4},
                {"product_id": None, "description": "red sofa", "quantity": 1},
            ],
            "note": "Delivery before 15 December if possible.",
        }
        data.update(overrides)
        return data

    def _wizard(self, order=None, text=EMAIL):
        return self.env["ag.ai.quote.wizard"].create({"email_text": text, "order_id": order.id if order else False})

    # ------------------------------------------------------------------ main path
    def test_email_becomes_a_quotation_for_the_known_customer(self):
        with patch(POST, return_value=anthropic_answer(self._answer())) as post:
            action = self._wizard().action_fill()
        order = self.env["sale.order"].browse(action["res_id"])
        self.assertEqual(order.partner_id, self.customer)
        products = order.order_line.filtered("product_id")
        self.assertEqual(products.mapped("product_id"), self.chair | self.table)
        self.assertEqual(products.mapped("product_uom_qty"), [20, 4])
        note = order.order_line.filtered(lambda line: line.display_type == "line_note")
        self.assertIn("red sofa", note.name, "what is not in the catalogue is kept in a note line")
        self.assertIn("Delivery before 15 December", str(order.note))
        # what was sent: the e-mail, the catalogue, the key in the header and never in the body
        request = post.call_args
        self.assertEqual(request.args[0], "https://api.anthropic.com/v1/messages")
        self.assertEqual(request.kwargs["headers"]["x-api-key"], "test-key")
        body = request.kwargs["json"]
        self.assertEqual(body["model"], "claude-haiku-5-5")
        self.assertIn("Office chair", body["system"])
        self.assertIn("20 office chairs", body["messages"][0]["content"])
        self.assertNotIn("test-key", json.dumps(body))

    def test_button_on_a_quotation_adds_the_lines_and_keeps_the_terms(self):
        order = self.env["sale.order"].create({"partner_id": self.customer.id, "note": "<p>Payment within 30 days.</p>"})
        with patch(POST, return_value=anthropic_answer(self._answer())):
            self._wizard(order).action_fill()
        self.assertEqual(len(order.order_line.filtered("product_id")), 2)
        self.assertIn("Payment within 30 days", str(order.note), "the terms already written must not be erased")
        self.assertIn("Delivery before 15 December", str(order.note))

    def test_answer_wrapped_in_text_or_code_fence_is_still_read(self):
        wrapped = "Here is the quotation:\n```json\n%s\n```" % json.dumps(self._answer())
        with patch(POST, return_value=anthropic_answer(wrapped)):
            action = self._wizard().action_fill()
        self.assertEqual(len(self.env["sale.order"].browse(action["res_id"]).order_line.filtered("product_id")), 2)

    def test_chatgpt_provider(self):
        self.env["ir.config_parameter"].sudo().set_param("ag_ai_quote.provider", "openai")
        with patch(POST, return_value=openai_answer(self._answer())) as post:
            action = self._wizard().action_fill()
        self.assertEqual(post.call_args.args[0], "https://api.openai.com/v1/chat/completions")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(len(self.env["sale.order"].browse(action["res_id"]).order_line.filtered("product_id")), 2)

    def test_new_customer_is_created_with_its_company(self):
        answer = self._answer(customer={"name": "Paul Rey", "company": "Rey Menuiserie Sàrl",
                                        "email": "paul@rey-menuiserie.example", "phone": "+41 21 555 12 12"})
        with patch(POST, return_value=anthropic_answer(answer)):
            action = self._wizard().action_fill()
        partner = self.env["sale.order"].browse(action["res_id"]).partner_id
        self.assertEqual(partner.name, "Paul Rey")
        self.assertEqual(partner.email, "paul@rey-menuiserie.example")
        self.assertEqual(partner.parent_id.name, "Rey Menuiserie Sàrl")
        self.assertTrue(partner.parent_id.is_company)

    def test_customer_is_not_confused_with_a_similar_address(self):
        """nadia_k@... must not be matched with nadiaxk@... (underscore is not a wildcard)."""
        other = self.env["res.partner"].create({"name": "Someone else", "email": "nadiaxk@firm.example"})
        answer = self._answer(customer={"name": "Nadia K", "company": None, "email": "nadia_k@firm.example", "phone": None})
        with patch(POST, return_value=anthropic_answer(answer)):
            action = self._wizard().action_fill()
        self.assertNotEqual(self.env["sale.order"].browse(action["res_id"]).partner_id, other)

    def test_product_that_is_not_for_sale_is_not_added(self):
        self.table.sale_ok = False
        with patch(POST, return_value=anthropic_answer(self._answer())):
            action = self._wizard().action_fill()
        order = self.env["sale.order"].browse(action["res_id"])
        self.assertEqual(order.order_line.filtered("product_id").product_id, self.chair)

    # ------------------------------------------------------------------ errors a user can understand
    def test_missing_key_explains_where_to_set_it(self):
        self.env["ir.config_parameter"].sudo().set_param("ag_ai_quote.api_key", False)
        with patch(POST) as post, self.assertRaises(UserError) as error:
            self._wizard().action_fill()
        post.assert_not_called()
        self.assertIn("Settings", str(error.exception))

    def test_refused_key_is_explained_without_technical_noise(self):
        refused = FakeResponse({"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}, 401)
        with patch(POST, return_value=refused), self.assertRaises(UserError) as error:
            self._wizard().action_fill()
        message = str(error.exception)
        self.assertIn("API key", message)
        self.assertNotIn("{", message, "no raw JSON in a message shown to a salesperson")

    def test_provider_message_is_shown_for_other_errors(self):
        bad = FakeResponse({"type": "error", "error": {"type": "not_found_error", "message": "model: claude-x does not exist"}}, 404)
        with patch(POST, return_value=bad), self.assertRaises(UserError) as error:
            self._wizard().action_fill()
        self.assertIn("claude-x does not exist", str(error.exception))
        self.assertNotIn("{", str(error.exception))

    def test_timeout_is_explained(self):
        with patch(POST, side_effect=requests.Timeout("read timed out")), self.assertRaises(UserError) as error:
            self._wizard().action_fill()
        self.assertIn("did not answer", str(error.exception))

    def test_refusal_and_truncated_answers_are_explained(self):
        with patch(POST, return_value=anthropic_answer("", stop_reason="refusal")), self.assertRaises(UserError) as error:
            self._wizard().action_fill()
        self.assertIn("declined", str(error.exception))
        cut = anthropic_answer('{"customer": {"name": "Nadia', stop_reason="max_tokens")
        with patch(POST, return_value=cut), self.assertRaises(UserError) as error:
            self._wizard().action_fill()
        self.assertIn("too long", str(error.exception))

    def test_unreadable_answer_gives_a_clear_message(self):
        with patch(POST, return_value=anthropic_answer("Sorry, I cannot help with that.")), self.assertRaises(UserError):
            self._wizard().action_fill()

    def test_unknown_customer_without_any_detail_is_explained(self):
        answer = self._answer(customer={"name": None, "company": None, "email": None, "phone": None})
        with patch(POST, return_value=anthropic_answer(answer)), self.assertRaises(UserError) as error:
            self._wizard().action_fill()
        self.assertIn("customer", str(error.exception))

    # ------------------------------------------------------------------ catalogue
    def test_large_catalogue_keeps_the_products_named_in_the_email(self):
        """With more products than the limit, the ones the e-mail talks about must still be offered to the AI."""
        from odoo.addons.ag_ai_quote_from_email.models import sale_order as module
        self.patch(module, "MAX_PRODUCTS", 5)
        pump = self.env["product.product"].create({"name": "Zentrifuga pump", "default_code": "ZP-9"})
        plate = self.env["product.product"].create({"name": "Quarzitex plate"})
        self.env["product.product"].create([{"name": "Filler product %s" % i} for i in range(12)])
        catalogue = self.env["sale.order"]._ag_ai_catalogue("Hello, we need 3 zentrifuga pumps and 2 quarzitex plates.")
        self.assertIn("%s | ZP-9 | Zentrifuga pump" % pump.id, catalogue)
        self.assertIn("Quarzitex plate", catalogue)
        self.assertEqual(len(catalogue.splitlines()), 5, "the list is filled up to the limit with recent products")

    def test_only_salespeople_reach_the_wizard(self):
        access = self.env["ir.model.access"].search([("model_id.model", "=", "ag.ai.quote.wizard")])
        self.assertTrue(access)
        self.assertTrue(all(rule.group_id for rule in access), "no public access to the wizard")

    def test_button_and_settings_are_in_the_screens(self):
        form = self.env.ref("sale.view_order_form").get_combined_arch()
        self.assertIn("Fill with AI", form)
        settings = self.env.ref("sale.res_config_settings_view_form").get_combined_arch()
        self.assertIn('name="ag_ai_api_key"', settings)
        self.assertIn('password="True"', settings)
