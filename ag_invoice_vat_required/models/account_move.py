from odoo import _, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = "account.move"

    def _post(self, soft=True):
        # Checked here and not in action_post: the list action "Confirm Entries", the invoices
        # that Odoo posts by itself at their date and the Point of Sale all call _post directly.
        for move in self:
            partner = move.partner_id.commercial_partner_id
            if (
                move.move_type in ("out_invoice", "out_refund")
                and partner.is_company
                and not partner.vat
                and not partner.vat_not_required
            ):
                raise UserError(_(
                    "%(partner)s is a company but has no Tax ID / VAT number.\n"
                    "Add it on the contact before posting %(document)s, or tick \"No Tax ID needed\" "
                    "on the contact if this company has none.",
                    partner=partner.display_name,
                    document=move.name if move.name and move.name != "/" else _("this invoice"),
                ))
        return super()._post(soft=soft)
