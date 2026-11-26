from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    quote_followup_enabled = fields.Boolean(string="Automatic quotation follow-up", default=True)
    quote_followup_days = fields.Integer(string="Follow-up after (days)", default=5)
    quote_followup_max = fields.Integer(string="Maximum follow-ups", default=2)
    quote_followup_start_date = fields.Date(
        string="Follow up quotations sent since",
        default=fields.Date.context_today,
        help="Quotations sent before this date are never followed up automatically. On a new installation "
             "it is set to the day the module is installed, so that old quotations are not chased by "
             "surprise. Leave it empty to follow up every sent quotation.",
    )
