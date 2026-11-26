from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    overdue_reminder_enabled = fields.Boolean(string="Overdue invoice reminders", default=True)
    overdue_reminder_first_days = fields.Integer(
        string="First reminder after (days)", default=3,
        help="Days of grace after the due date before the first reminder: a transfer made on the "
             "due date takes a few days to reach your bank statement.",
    )
    overdue_reminder_days = fields.Integer(string="Days between reminders", default=7)
    overdue_reminder_max = fields.Integer(string="Maximum reminders", default=3)
    overdue_reminder_start_date = fields.Date(
        string="Remind invoices due since",
        default=fields.Date.context_today,
        help="Invoices due before this date are never reminded automatically. On a new installation it "
             "is set to the day the module is installed, so that old unpaid invoices are not chased by "
             "surprise. Leave it empty to remind every unpaid invoice.",
    )
