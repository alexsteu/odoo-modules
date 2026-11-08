from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    quote_followup_enabled = fields.Boolean(string="Automatic quotation follow-up", default=True)
    quote_followup_days = fields.Integer(string="Follow-up after (days)", default=5)
    quote_followup_max = fields.Integer(string="Maximum follow-ups", default=2)
