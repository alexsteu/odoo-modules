def migrate(cr, version):
    """A database that already ran 1.0.x keeps following up the quotations it was following up.

    The start date added in 1.1.0 takes its default when the column is created: the current
    day. That is right for a new installation (old quotations are not chased by surprise)
    and wrong for an upgrade, where it would silently stop the follow-ups in progress.
    An empty date means "no limit", which is what 1.0.x did.

    1.0.x counted the delay from the quotation date. The quotations already sent keep that
    reference, since the day they were sent was not recorded.

    The folder is named 1.1.0, without the Odoo series, so that the script does not run
    again when a database installed in 17.0.1.1.0 moves to 18.0.1.1.0.
    """
    if not version:
        return
    cr.execute("UPDATE res_company SET quote_followup_start_date = NULL")
    cr.execute(
        """
        UPDATE sale_order
           SET followup_sent_date = date_order
         WHERE state = 'sent'
           AND followup_sent_date IS NULL
        """
    )
