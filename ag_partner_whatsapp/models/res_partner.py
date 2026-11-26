import re

from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    whatsapp_url = fields.Char(string="WhatsApp", compute="_compute_whatsapp_url")

    @api.depends("phone", "mobile", "country_id")
    def _compute_whatsapp_url(self):
        for partner in self:
            digits = partner._ag_whatsapp_digits()
            partner.whatsapp_url = f"https://wa.me/{digits}" if digits else False

    def _ag_whatsapp_digits(self):
        """Digits of the first usable number (mobile, then phone) in international format."""
        self.ensure_one()
        for fname in ("mobile", "phone"):
            raw = self[fname] if fname in self._fields else False
            if not raw:
                continue
            number = re.sub(r"[^0-9+]", "", raw)
            if number.startswith("00"):
                number = "+" + number[2:]
            if not number.startswith("+"):
                number = self._ag_whatsapp_from_national(raw, number)
            digits = number.lstrip("+")
            if number.startswith("+") and digits.isdigit() and 8 <= len(digits) <= 15:
                return digits
        return False

    def _ag_whatsapp_from_national(self, raw, number):
        """Turn `076 488 27 10` into `+41764882710` with the country of the contact (or of the company)."""
        country = self.country_id or self.env.company.country_id
        if not country or not number:
            return ""
        if hasattr(self, "_phone_format"):          # Odoo's phone validation is installed
            try:
                formatted = self._phone_format(number=raw, country=country, force_format="E164")
            except Exception:                        # never block the contact form for a link
                formatted = False
            if formatted and formatted.startswith("+"):
                return formatted
        # Simple rule for countries where national numbers start with one 0 (CH, FR, BE, DE, AT, NL, UK...)
        if number.startswith("0") and country.phone_code and country.code != "IT":
            return "+%s%s" % (country.phone_code, number[1:])
        return ""
