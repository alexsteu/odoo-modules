from odoo import _, fields, models
from odoo.exceptions import UserError


class AiQuoteWizard(models.TransientModel):
    _name = "ag.ai.quote.wizard"
    _description = "AI quotation from e-mail"

    email_text = fields.Text(string="Customer e-mail", required=True)
    order_id = fields.Many2one("sale.order", string="Quotation")

    def action_fill(self):
        self.ensure_one()
        SaleOrder = self.env["sale.order"]
        data = SaleOrder._ag_ai_parse(self.email_text)
        order = self.order_id
        if not order:
            partner = SaleOrder._ag_ai_find_partner(data.get("customer") or {})
            if not partner:
                raise UserError(_("The AI could not find who the customer is. Open a quotation for that customer and use the AI button there."))
            order = SaleOrder.create({"partner_id": partner.id})
        result = order._ag_ai_apply(data)
        order.message_post(body=_("Quotation filled by AI from a customer e-mail: %(added)s line(s) added, %(missing)s to check.", **result))
        return {
            "type": "ir.actions.act_window",
            "res_model": "sale.order",
            "res_id": order.id,
            "view_mode": "form",
            "target": "current",
        }
