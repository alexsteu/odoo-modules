from odoo import api, fields, models


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    line_number = fields.Integer(string="#", compute="_compute_line_number")

    @api.depends("order_id.order_line", "sequence", "display_type")
    def _compute_line_number(self):
        for order in self.mapped("order_id"):
            number = 0
            for line in order.order_line.sorted(lambda l: (l.sequence, l.id or 0)):
                if line.display_type:
                    line.line_number = 0
                else:
                    number += 1
                    line.line_number = number
        for line in self.filtered(lambda l: not l.order_id):
            line.line_number = 0
