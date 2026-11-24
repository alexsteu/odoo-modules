from odoo import Command
from odoo.tests import TransactionCase, tagged, new_test_user


@tagged("post_install", "-at_install")
class TestMassConfirm(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Customer"})
        cls.product = cls.env["product.product"].create({"name": "Chair", "list_price": 50})
        cls.action = cls.env.ref("ag_sale_mass_confirm.action_sale_mass_confirm")

    def _quotation(self):
        return self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "order_line": [Command.create({"product_id": self.product.id, "product_uom_qty": 1})],
        })

    def _run(self, orders, user=None):
        action = self.action.with_user(user) if user else self.action
        return action.with_context(active_model="sale.order", active_ids=orders.ids).run()

    def test_draft_and_sent_quotations_are_confirmed(self):
        draft, sent = self._quotation(), self._quotation()
        sent.action_quotation_sent()
        self._run(draft | sent)
        self.assertEqual((draft | sent).mapped("state"), ["sale", "sale"])

    def test_confirmed_and_cancelled_orders_are_left_alone(self):
        draft, confirmed, cancelled = self._quotation(), self._quotation(), self._quotation()
        confirmed.action_confirm()
        cancelled._action_cancel()
        result = self._run(draft | confirmed | cancelled)
        self.assertEqual(draft.state, "sale")
        self.assertEqual(confirmed.state, "sale")
        self.assertEqual(cancelled.state, "cancel")
        self.assertEqual(result["tag"], "display_notification")
        self.assertIn("1", result["params"]["message"])
        self.assertIn("2", result["params"]["message"])

    def test_one_blocked_quotation_does_not_stop_the_others(self):
        """A quotation that cannot be confirmed is reported; the others are still confirmed."""
        good, blocked = self._quotation(), self._quotation()
        original = type(self.env["sale.order"]).action_confirm

        def action_confirm(orders):
            if blocked in orders:
                from odoo.exceptions import UserError
                raise UserError("Customer on credit hold")
            return original(orders)

        self.patch(type(self.env["sale.order"]), "action_confirm", action_confirm)
        result = self._run(good | blocked)
        self.assertEqual(good.state, "sale")
        self.assertEqual(blocked.state, "draft")
        self.assertIn(blocked.name, result["params"]["message"])
        self.assertIn("Customer on credit hold", result["params"]["message"])

    def test_salesperson_can_use_it(self):
        salesman = new_test_user(self.env, login="mass_salesman", groups="sales_team.group_sale_salesman")
        quotation = self._quotation()
        quotation.user_id = salesman
        self._run(quotation, user=salesman)
        self.assertEqual(quotation.state, "sale")

    def test_action_is_in_the_list_menu_only(self):
        self.assertEqual(self.action.binding_model_id.model, "sale.order")
        self.assertEqual(self.action.binding_view_types, "list")
