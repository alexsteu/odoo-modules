from odoo import api, fields, models


class CrmLead(models.Model):
    _inherit = "crm.lead"

    age_days = fields.Integer(string="Age (days)", compute="_compute_age_days")

    @api.depends("create_date")
    def _compute_age_days(self):
        today = fields.Date.context_today(self)
        for lead in self:
            lead.age_days = (today - lead.create_date.date()).days if lead.create_date else 0
