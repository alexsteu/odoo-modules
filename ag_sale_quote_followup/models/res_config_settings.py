from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    quote_followup_enabled = fields.Boolean(
        related="company_id.quote_followup_enabled", readonly=False
    )
    quote_followup_days = fields.Integer(
        related="company_id.quote_followup_days", readonly=False
    )
    quote_followup_max = fields.Integer(
        related="company_id.quote_followup_max", readonly=False
    )
    quote_followup_start_date = fields.Date(
        related="company_id.quote_followup_start_date", readonly=False
    )
