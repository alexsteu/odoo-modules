from collections import defaultdict

from odoo import fields, models

MANAGERS = "project.group_project_manager"


class ProjectProject(models.Model):
    _inherit = "project.project"

    # The figures are computed with elevated rights (analytic lines, hourly costs): the fields
    # themselves are reserved to project managers, whatever the way they are read.
    ag_hours_spent = fields.Float(
        string="Hours spent", compute="_compute_ag_profitability", digits=(16, 2), groups=MANAGERS)
    ag_timesheet_cost = fields.Monetary(
        string="Timesheet cost", compute="_compute_ag_profitability", groups=MANAGERS)
    ag_other_costs = fields.Monetary(
        string="Other costs", compute="_compute_ag_profitability", groups=MANAGERS)
    ag_revenue = fields.Monetary(
        string="Revenue", compute="_compute_ag_profitability", groups=MANAGERS)
    ag_margin = fields.Monetary(
        string="Margin", compute="_compute_ag_profitability", groups=MANAGERS)
    ag_margin_percent = fields.Float(
        string="Margin %", compute="_compute_ag_profitability", digits=(16, 1), groups=MANAGERS)

    def _ag_analytic_account(self):
        self.ensure_one()
        # Odoo 18 uses account_id, Odoo 17 analytic_account_id
        return self["account_id"] if "account_id" in self._fields else self["analytic_account_id"]

    def _compute_ag_profitability(self):
        """Read everything in a handful of grouped queries, whatever the number of projects.

        * Hours and timesheet cost: analytic lines linked to the project (timesheets).
        * Revenue: customer invoices and credit notes on the analytic account of the project
          (a credit note lowers the revenue, it is not a cost).
        * Other costs: vendor bills and refunds on that account (a refund lowers the costs).
        * Analytic entries that come from neither: positive amounts are revenue, negative ones costs.
        """
        Line = self.env["account.analytic.line"].sudo()
        # `_origin` gives the saved record while the form is being edited: the figures stay on screen
        project_ids = self._origin.ids

        timesheets = {}
        if project_ids:
            for project, hours, amount in Line._read_group(
                [("project_id", "in", project_ids)], ["project_id"], ["unit_amount:sum", "amount:sum"]
            ):
                timesheets[project.id] = (hours or 0.0, -(amount or 0.0))

        accounts = {project: project._origin._ag_analytic_account() for project in self if project._origin}
        account_ids = list({account.id for account in accounts.values() if account})
        revenue, costs = defaultdict(float), defaultdict(float)
        if account_ids:
            base = [("account_id", "in", account_ids), ("project_id", "=", False)]
            documents = ("invoice", "vendor_bill")
            for account, category, amount in Line._read_group(
                base + [("category", "in", documents)], ["account_id", "category"], ["amount:sum"]
            ):
                if category == "invoice":
                    revenue[account.id] += amount or 0.0
                else:
                    costs[account.id] -= amount or 0.0
            for account, amount in Line._read_group(
                base + [("category", "not in", documents), ("amount", ">", 0)], ["account_id"], ["amount:sum"]
            ):
                revenue[account.id] += amount or 0.0
            for account, amount in Line._read_group(
                base + [("category", "not in", documents), ("amount", "<", 0)], ["account_id"], ["amount:sum"]
            ):
                costs[account.id] -= amount or 0.0

        for project in self:
            hours, timesheet_cost = timesheets.get(project._origin.id, (0.0, 0.0))
            account = accounts.get(project)
            project_revenue = revenue[account.id] if account else 0.0
            other_costs = costs[account.id] if account else 0.0
            margin = project_revenue - timesheet_cost - other_costs
            project.ag_hours_spent = hours
            project.ag_timesheet_cost = timesheet_cost
            project.ag_other_costs = other_costs
            project.ag_revenue = project_revenue
            project.ag_margin = margin
            project.ag_margin_percent = (margin / project_revenue * 100) if project_revenue > 0 else 0.0
