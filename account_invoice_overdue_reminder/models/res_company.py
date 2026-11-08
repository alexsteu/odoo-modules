from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    overdue_reminder_enabled = fields.Boolean(string="Overdue invoice reminders", default=True)
    overdue_reminder_days = fields.Integer(string="Days between reminders", default=7)
    overdue_reminder_max = fields.Integer(string="Maximum reminders", default=3)
