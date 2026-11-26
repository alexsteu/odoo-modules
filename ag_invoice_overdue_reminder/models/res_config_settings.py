from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    overdue_reminder_enabled = fields.Boolean(
        related="company_id.overdue_reminder_enabled", readonly=False
    )
    overdue_reminder_first_days = fields.Integer(
        related="company_id.overdue_reminder_first_days", readonly=False
    )
    overdue_reminder_days = fields.Integer(
        related="company_id.overdue_reminder_days", readonly=False
    )
    overdue_reminder_max = fields.Integer(
        related="company_id.overdue_reminder_max", readonly=False
    )
    overdue_reminder_start_date = fields.Date(
        related="company_id.overdue_reminder_start_date", readonly=False
    )
