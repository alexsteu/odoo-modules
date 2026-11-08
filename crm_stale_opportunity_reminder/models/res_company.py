from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    stale_opportunity_enabled = fields.Boolean(string="Forgotten opportunity reminder", default=True)
    stale_opportunity_days = fields.Integer(string="Inactive for (days)", default=10)
