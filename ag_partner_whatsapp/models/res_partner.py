import re

from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    whatsapp_url = fields.Char(string="WhatsApp", compute="_compute_whatsapp_url")

    @api.depends("phone", "mobile")
    def _compute_whatsapp_url(self):
        for partner in self:
            number = re.sub(r"[^0-9+]", "", partner.mobile or partner.phone or "")
            if number.startswith("00"):
                number = "+" + number[2:]
            digits = number.lstrip("+")
            partner.whatsapp_url = f"https://wa.me/{digits}" if len(digits) >= 8 and number.startswith("+") else False
