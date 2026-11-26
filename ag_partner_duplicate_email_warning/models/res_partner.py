from odoo import _, api, models, tools


class ResPartner(models.Model):
    _inherit = "res.partner"

    def _ag_duplicate_email_domain(self, email):
        """Exact, case-insensitive match on the address itself.

        `"Garage Rochat" <contact@rochat.ch>` and `Contact@Rochat.ch` are the same address;
        `john_doe@` and `johnxdoe@` are not (`_` and `%` are wildcards for ilike).
        """
        normalized = tools.email_normalize(email)
        if normalized and "email_normalized" in self._fields:
            return [("email_normalized", "=", normalized)]
        escaped = email.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return [("email", "=ilike", escaped)]

    @api.onchange("email")
    def _onchange_email_duplicate_warning(self):
        email = (self.email or "").strip()
        if not email:
            return
        domain = self._ag_duplicate_email_domain(email)
        if self._origin.id:
            domain.append(("id", "!=", self._origin.id))
        existing = self.env["res.partner"].search(domain, limit=3)
        if existing:
            return {"warning": {
                "title": _("This e-mail already exists"),
                "message": _("Already used by: %s. You may be creating a duplicate.",
                             ", ".join(existing.mapped("display_name"))),
            }}
