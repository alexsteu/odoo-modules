from odoo import _, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = "account.move"

    def action_post(self):
        for move in self:
            partner = move.partner_id.commercial_partner_id
            if move.move_type in ("out_invoice", "out_refund") and partner.is_company and not partner.vat:
                raise UserError(_(
                    "%s is a company but has no Tax ID / VAT number. Please add it on the contact before posting %s.",
                    partner.display_name, move.name or _("this invoice"),
                ))
        return super().action_post()
