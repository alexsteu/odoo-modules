from odoo import _, api, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    @api.onchange("email")
    def _onchange_email_duplicate_warning(self):
        email = (self.email or "").strip()
        if not email:
            return
        domain = [("email", "=ilike", email)]
        if self._origin.id:
            domain.append(("id", "!=", self._origin.id))
        existing = self.env["res.partner"].search(domain, limit=3)
        if existing:
            return {"warning": {
                "title": _("This e-mail already exists"),
                "message": _("Already used by: %s. You may be creating a duplicate.",
                             ", ".join(existing.mapped("display_name"))),
            }}
