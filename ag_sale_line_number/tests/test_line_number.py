from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLineNumber(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Customer"})
        cls.product = cls.env["product.product"].create({"name": "Chair", "list_price": 50})

    def _line(self, sequence, **values):
        values.setdefault("product_id", self.product.id)
        return Command.create(dict(values, sequence=sequence))

    def test_products_are_numbered_and_sections_skipped(self):
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "order_line": [
                Command.create({"display_type": "line_section", "name": "Ground floor", "sequence": 1}),
                self._line(2),
                self._line(3),
                Command.create({"display_type": "line_note", "name": "Delivered on Monday", "sequence": 4}),
                self._line(5),
            ],
        })
        numbers = order.order_line.sorted("sequence").mapped("line_number")
        self.assertEqual(numbers, [0, 1, 2, 0, 3])

    def test_numbers_follow_the_new_order_after_a_move(self):
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "order_line": [self._line(1), self._line(2), self._line(3)],
        })
        first, second, third = order.order_line.sorted("sequence")
        third.sequence = 0
        self.assertEqual(third.line_number, 1)
        self.assertEqual(first.line_number, 2)
        self.assertEqual(second.line_number, 3)

    def test_numbers_close_the_gap_after_a_deletion(self):
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "order_line": [self._line(1), self._line(2), self._line(3)],
        })
        first, second, third = order.order_line.sorted("sequence")
        second.unlink()
        self.assertEqual((first | third).mapped("line_number"), [1, 2])

    def test_column_is_in_the_quotation_form(self):
        arch = self.env.ref("sale.view_order_form").get_combined_arch()
        self.assertIn('name="line_number"', arch)

    def test_number_is_printed_on_the_quotation(self):
        """The customer must see the numbers too, otherwise 'line 4' means nothing to them."""
        arch = self.env.ref("sale.report_saleorder_document").get_combined_arch()
        self.assertIn("line_number", arch)
