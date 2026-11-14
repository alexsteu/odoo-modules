from odoo import fields, models


class ProjectProject(models.Model):
    _inherit = "project.project"

    ag_hours_spent = fields.Float(string="Hours spent", compute="_compute_ag_profitability", digits=(16, 2))
    ag_timesheet_cost = fields.Monetary(string="Timesheet cost", compute="_compute_ag_profitability")
    ag_other_costs = fields.Monetary(string="Other costs", compute="_compute_ag_profitability")
    ag_revenue = fields.Monetary(string="Revenue", compute="_compute_ag_profitability")
    ag_margin = fields.Monetary(string="Margin", compute="_compute_ag_profitability")
    ag_margin_percent = fields.Float(string="Margin %", compute="_compute_ag_profitability", digits=(16, 1))

    def _ag_analytic_account(self):
        self.ensure_one()
        # Odoo 18 uses account_id, Odoo 17 analytic_account_id
        return self["account_id"] if "account_id" in self._fields else self["analytic_account_id"]

    def _compute_ag_profitability(self):
        Line = self.env["account.analytic.line"].sudo()
        for project in self:
            hours = cost = other = revenue = 0.0
            if project.id:
                for unit, amount in Line._read_group(
                    [("project_id", "=", project.id)], [], ["unit_amount:sum", "amount:sum"]
                ):
                    hours, cost = unit or 0.0, -(amount or 0.0)
                account = project._ag_analytic_account()
                if account:
                    base = [("account_id", "=", account.id), ("project_id", "=", False)]
                    for (amount,) in Line._read_group(base + [("amount", ">", 0)], [], ["amount:sum"]):
                        revenue = amount or 0.0
                    for (amount,) in Line._read_group(base + [("amount", "<", 0)], [], ["amount:sum"]):
                        other = -(amount or 0.0)
            margin = revenue - cost - other
            project.ag_hours_spent = hours
            project.ag_timesheet_cost = cost
            project.ag_other_costs = other
            project.ag_revenue = revenue
            project.ag_margin = margin
            project.ag_margin_percent = (margin / revenue * 100) if revenue else 0.0
