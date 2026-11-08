from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    stale_opportunity_enabled = fields.Boolean(
        related="company_id.stale_opportunity_enabled", readonly=False
    )
    stale_opportunity_days = fields.Integer(
        related="company_id.stale_opportunity_days", readonly=False
    )
