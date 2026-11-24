from odoo import _, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def action_ag_mass_confirm(self):
        """Confirm the selected quotations one by one and tell the user what happened.

        A quotation that cannot be confirmed (blocking rule, missing data...) is reported with
        the reason; it never prevents the other ones from being confirmed.
        """
        quotations = self.filtered(lambda order: order.state in ("draft", "sent"))
        skipped = len(self) - len(quotations)
        confirmed, failed = 0, []
        for quotation in quotations:
            try:
                with self.env.cr.savepoint():
                    quotation.action_confirm()
                confirmed += 1
            except UserError as error:
                failed.append("%s: %s" % (quotation.name, error.args[0] if error.args else error))
        parts = [_("%s confirmed.", confirmed)]
        if skipped:
            parts.append(_("%s skipped (already confirmed or cancelled).", skipped))
        if failed:
            parts.append(_("%s not confirmed:", len(failed)) + " " + " | ".join(failed))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Quotations confirmed") if confirmed else _("No quotation confirmed"),
                "message": " ".join(parts),
                "type": "warning" if failed else "success",
                "sticky": bool(failed),
                "next": {"type": "ir.actions.client", "tag": "soft_reload"} if confirmed
                        else {"type": "ir.actions.act_window_close"},
            },
        }
