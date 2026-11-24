def migrate(cr, version):
    """A database that already ran 1.0.x keeps reminding the invoices it was reminding.

    The start date added in 1.1.0 takes its default when the column is created: the current
    day. That is right for a new installation (old unpaid invoices are not chased by surprise)
    and wrong for an upgrade, where it would silently stop the reminders in progress.
    An empty date means "no limit", which is what 1.0.x did.

    The folder is named 1.1.0, without the Odoo series, so that the script does not run
    again when a database installed in 17.0.1.1.0 moves to 18.0.1.1.0.
    """
    if not version:
        return
    cr.execute("UPDATE res_company SET overdue_reminder_start_date = NULL")
