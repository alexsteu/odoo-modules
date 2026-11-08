from datetime import timedelta

from odoo import _, api, fields, models


class CrmLead(models.Model):
    _inherit = "crm.lead"

    @api.model
    def _cron_remind_stale_opportunities(self):
        now = fields.Datetime.now()
        for company in self.env["res.company"].search([("stale_opportunity_enabled", "=", True)]):
            days = max(company.stale_opportunity_days, 1)
            limit_date = now - timedelta(days=days)
            leads = self.search([
                ("company_id", "in", (company.id, False)),
                ("type", "=", "opportunity"),
                ("active", "=", True),
                ("stage_id.is_won", "=", False),
                ("user_id", "!=", False),
                ("activity_ids", "=", False),
                ("write_date", "<", limit_date),
            ])
            for lead in leads:
                lead.activity_schedule(
                    "mail.mail_activity_data_todo",
                    date_deadline=fields.Date.context_today(self),
                    summary=_("No news for %s days: follow up", days),
                    user_id=lead.user_id.id,
                )
