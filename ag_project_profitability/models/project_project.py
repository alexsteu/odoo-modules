from collections import defaultdict

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

    def _ag_analytic_columns(self, accounts):
        """{column of the analytic lines: ids of the analytic accounts stored in that column}.

        In Odoo 17 the analytic account of a project can belong to any analytic plan, and each plan
        has its own column on the analytic lines: `account_id` for the plan of the projects,
        `x_plan<id>_id` for the other ones.
        """
        columns = defaultdict(set)
        for account in accounts:
            if account:
                # sudo: analytic accounts are only readable by the analytic accounting group
                columns[account.sudo().plan_id._column_name()].add(account.id)
        return {column: list(account_ids) for column, account_ids in columns.items()}

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
        revenue, costs = defaultdict(float), defaultdict(float)
        documents = ("invoice", "vendor_bill")
        for column, account_ids in self._ag_analytic_columns(accounts.values()).items():
            base = [(column, "in", account_ids), ("project_id", "=", False)]
            for account, category, amount in Line._read_group(
                base + [("category", "in", documents)], [column, "category"], ["amount:sum"]
            ):
                if category == "invoice":
                    revenue[account.id] += amount or 0.0
                else:
                    costs[account.id] -= amount or 0.0
            for account, amount in Line._read_group(
                base + [("category", "not in", documents), ("amount", ">", 0)], [column], ["amount:sum"]
            ):
                revenue[account.id] += amount or 0.0
            for account, amount in Line._read_group(
                base + [("category", "not in", documents), ("amount", "<", 0)], [column], ["amount:sum"]
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
