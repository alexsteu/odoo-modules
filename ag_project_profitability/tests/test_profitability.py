from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests import new_test_user, tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestProjectProfitability(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env["hr.employee"].create({
            "name": "Camille Technician",
            "hourly_cost": 50.0,
        })
        cls.project = cls.env["project.project"].create({
            "name": "Kitchen renovation",
            "allow_timesheets": True,
        })
        cls.task = cls.env["project.task"].create({
            "name": "Installation",
            "project_id": cls.project.id,
        })

    @classmethod
    def _analytic(cls, project):
        return project._ag_analytic_account()

    def _timesheet(self, hours, project=None):
        project = project or self.project
        return self.env["account.analytic.line"].create({
            "name": "Work on site",
            "project_id": project.id,
            "task_id": self.task.id if project == self.project else False,
            "employee_id": self.employee.id,
            "unit_amount": hours,
            "date": fields.Date.today(),
        })

    def _invoice(self, move_type, amount, project=None):
        project = project or self.project
        account = self._analytic(project)
        move = self.env["account.move"].create({
            "move_type": move_type,
            "partner_id": self.partner_a.id,
            "invoice_date": fields.Date.today(),
            "invoice_line_ids": [Command.create({
                "name": "Line",
                "quantity": 1,
                "price_unit": amount,
                "tax_ids": [Command.clear()],
                "analytic_distribution": {str(account.id): 100},
            })],
        })
        move.action_post()
        return move

    def test_empty_project_shows_zero(self):
        self.assertEqual(self.project.ag_hours_spent, 0.0)
        self.assertEqual(self.project.ag_timesheet_cost, 0.0)
        self.assertEqual(self.project.ag_revenue, 0.0)
        self.assertEqual(self.project.ag_other_costs, 0.0)
        self.assertEqual(self.project.ag_margin, 0.0)
        self.assertEqual(self.project.ag_margin_percent, 0.0)

    def test_hours_and_timesheet_cost(self):
        self._timesheet(3.0)
        self._timesheet(1.5)
        self.project.invalidate_recordset()
        self.assertAlmostEqual(self.project.ag_hours_spent, 4.5)
        self.assertAlmostEqual(self.project.ag_timesheet_cost, 225.0)
        self.assertAlmostEqual(self.project.ag_margin, -225.0)
        self.assertEqual(self.project.ag_margin_percent, 0.0, "no revenue: no percentage")

    def test_revenue_other_costs_and_margin(self):
        self.assertTrue(self._analytic(self.project), "a timesheet project gets an analytic account")
        self._timesheet(4.0)                      # 200 of timesheet cost
        self._invoice("out_invoice", 1000.0)      # revenue
        self._invoice("in_invoice", 300.0)        # other costs
        self.project.invalidate_recordset()
        self.assertAlmostEqual(self.project.ag_revenue, 1000.0)
        self.assertAlmostEqual(self.project.ag_other_costs, 300.0)
        self.assertAlmostEqual(self.project.ag_timesheet_cost, 200.0)
        self.assertAlmostEqual(self.project.ag_margin, 500.0)
        self.assertAlmostEqual(self.project.ag_margin_percent, 50.0)

    def test_credit_note_reduces_revenue(self):
        self._invoice("out_invoice", 1000.0)
        self._invoice("out_refund", 200.0)
        self.project.invalidate_recordset()
        self.assertAlmostEqual(self.project.ag_revenue, 800.0)
        self.assertAlmostEqual(self.project.ag_other_costs, 0.0)
        self.assertAlmostEqual(self.project.ag_margin, 800.0)

    def test_projects_do_not_mix(self):
        other = self.env["project.project"].create({"name": "Other site", "allow_timesheets": True})
        self._timesheet(2.0)
        self._timesheet(7.0, project=other)
        self._invoice("out_invoice", 400.0, project=other)
        (self.project | other).invalidate_recordset()
        self.assertAlmostEqual(self.project.ag_hours_spent, 2.0)
        self.assertAlmostEqual(self.project.ag_revenue, 0.0)
        self.assertAlmostEqual(other.ag_hours_spent, 7.0)
        self.assertAlmostEqual(other.ag_revenue, 400.0)

    def test_project_without_analytic_account(self):
        project = self.env["project.project"].create({"name": "No timesheet", "allow_timesheets": False})
        account_field = "account_id" if "account_id" in project._fields else "analytic_account_id"
        project[account_field] = False
        self.assertEqual(project.ag_revenue, 0.0)
        self.assertEqual(project.ag_margin, 0.0)

    def test_list_reads_many_projects_with_few_queries(self):
        projects = self.project
        for index in range(15):
            projects |= self.env["project.project"].create({"name": "P%s" % index, "allow_timesheets": True})
        self._timesheet(1.0)
        projects.invalidate_recordset()
        self.env.flush_all()
        start = self.env.cr.sql_log_count
        projects.mapped("ag_margin")
        used = self.env.cr.sql_log_count - start
        self.assertLess(used, 12, "the list view must not run several queries per project (%s used)" % used)

    def test_figures_are_reserved_to_project_managers(self):
        """Costs and margins are computed with elevated rights: a project user must not read them."""
        self._timesheet(2.0)
        user = new_test_user(self.env, login="ag_project_user", groups="project.group_project_user")
        manager = new_test_user(self.env, login="ag_project_manager", groups="project.group_project_manager")
        figures = ["ag_hours_spent", "ag_timesheet_cost", "ag_other_costs", "ag_revenue", "ag_margin",
                   "ag_margin_percent"]

        as_user = self.project.with_user(user)
        self.assertTrue(as_user.read(["name"]), "the project itself stays readable")
        known = as_user.fields_get()
        for name in figures:
            self.assertNotIn(name, known)
            with self.assertRaises(AccessError):
                as_user.read([name])
        with self.assertRaises(AccessError):
            self.env["project.project"].with_user(user).search_read([("id", "=", self.project.id)], ["ag_margin"])

        data = self.project.with_user(manager).read(figures)[0]
        self.assertAlmostEqual(data["ag_hours_spent"], 2.0)
        self.assertAlmostEqual(data["ag_timesheet_cost"], 100.0)

        # the project user still opens the form and the list of projects, without the figures
        kinds = dict(self.env["ir.ui.view"]._fields["type"].selection)
        listing = "list" if "list" in kinds else "tree"
        wanted = [(self.env.ref("project.edit_project").id, "form"),
                  (self.env.ref("project.view_project").id, listing)]
        for_user = self.env["project.project"].with_user(user).get_views(wanted)["views"]
        for_manager = self.env["project.project"].with_user(manager).get_views(wanted)["views"]
        for kind in ("form", listing):
            self.assertNotIn("ag_margin", for_user[kind]["arch"])
            self.assertIn("ag_margin", for_manager[kind]["arch"])

    def test_views_show_the_figures(self):
        form = self.env.ref("project.edit_project").get_combined_arch()
        self.assertIn('name="ag_profitability"', form)
        self.assertIn('name="ag_margin_percent"', form)
        listing = self.env.ref("project.view_project").get_combined_arch()
        self.assertIn('name="ag_hours_spent"', listing)
        self.assertIn('name="ag_margin"', listing)

    def test_analytic_accounting_can_be_switched_on_from_the_project_settings(self):
        """Without Odoo's option Analytic Accounting, the column where an invoice is linked to the
        project stays hidden and the revenue stays at 0. On Odoo Community, Odoo shows the option
        to users with full accounting rights only: the module offers it in the Project settings."""
        admin = new_test_user(
            self.env, "ag_settings_admin",
            groups="base.group_system,project.group_project_manager,account.group_account_invoice")
        self.assertFalse(admin.has_group("account.group_account_user"), "no full accounting rights")
        Settings = self.env["res.config.settings"].with_user(admin)
        settings_screen = Settings.get_view(view_type="form")["arch"]
        self.assertIn('id="ag_analytic_accounting_setting"', settings_screen)
        self.assertEqual(settings_screen.count('name="group_analytic_accounting"'), 1)

        invoice_screen = self.env["account.move"].with_user(admin).get_view(view_type="form")["arch"]
        if admin.has_group("analytic.group_analytic_accounting"):
            return      # the option is already on in this database
        self.assertNotIn("analytic_distribution", invoice_screen)
        Settings.create({"group_analytic_accounting": True}).execute()
        invoice_screen = self.env["account.move"].with_user(admin).get_view(view_type="form")["arch"]
        self.assertIn("analytic_distribution", invoice_screen)
