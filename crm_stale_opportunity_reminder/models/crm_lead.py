from datetime import timedelta

from odoo import _, api, fields, models


class CrmLead(models.Model):
    _inherit = "crm.lead"

    @api.model
    def _cron_remind_stale_opportunities(self):
        """Schedule a to-do on open opportunities nobody touched for N days.

        "Touched" means: the opportunity was changed, or something was written in its chatter
        (message, note, activity marked as done). So a salesperson who has just followed up is
        not reminded again the next morning.
        """
        now = fields.Datetime.now()
        Message = self.env["mail.message"].sudo()
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
            if not leads:
                continue
            recent = Message._read_group(
                [("model", "=", "crm.lead"), ("res_id", "in", leads.ids), ("date", ">=", limit_date)],
                ["res_id"],
            )
            recently_discussed = {res_id for (res_id,) in recent}
            for lead in leads:
                if lead.id in recently_discussed:
                    continue
                lead.activity_schedule(
                    "mail.mail_activity_data_todo",
                    date_deadline=fields.Date.context_today(self),
                    summary=_("No news for %s days: follow up", days),
                    user_id=lead.user_id.id,
                )
