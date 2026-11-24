# Free Odoo 17 modules for SMEs

By Alexandre Gabriel, independent Odoo developer. Tested on Odoo 17 (Community).

- `ag_ai_quote_from_email`: Paste a customer e-mail: AI finds the customer and your products and fills the quotation for you.
- `ag_ai_vendor_bill`: Upload a supplier invoice PDF or photo: AI reads it and fills the vendor bill, also in Odoo Community.
- `ag_crm_lead_age`: Show how many days each opportunity has been open in the CRM list.
- `ag_invoice_overdue_reminder`: Automatically e-mail customers whose invoices are overdue, in Odoo Community.
- `ag_invoice_vat_required`: Block posting a customer invoice to a company that has no VAT number.
- `ag_partner_customer_since`: Show the date of the first confirmed sales order on each customer.
- `ag_partner_duplicate_email_warning`: Warn when you type an e-mail that already belongs to another contact.
- `ag_partner_whatsapp`: Open a WhatsApp chat with a contact in one click from its phone number.
- `ag_product_brand`: Add a brand to your products, then filter and group sales and products by brand.
- `ag_product_margin_percent`: See the margin percentage of each product next to its sales price.
- `ag_project_profitability`: See hours spent, timesheet cost, revenue and margin of each project, also in Odoo Community.
- `ag_sale_expired_quote_banner`: Show a clear warning on quotations whose validity date has passed.
- `ag_sale_line_number`: Show a line number on each sales order and quotation line.
- `ag_sale_mass_confirm`: Select quotations in the list and confirm them all in one click.
- `ag_sale_minimum_order`: Prevent the confirmation of sales orders below a minimum amount.
- `ag_sale_quote_followup`: Send an automatic reminder e-mail to customers who did not answer a quotation.
- `ag_sale_require_customer_ref`: Block the confirmation of a sales order without customer reference for customers who require a PO number.
- `crm_stale_opportunity_reminder`: Create a follow-up activity on CRM opportunities nobody touched for a while.

## Tests

Every module comes with automated tests (171 in total on this branch). To run the tests of one module on a test database:

    odoo-bin -d <test database> -i <module> --test-tags /<module> --stop-after-init

The two AI modules are tested with simulated answers of the AI providers: the tests never call a paid service.

## Upgrading from version 17.0.1.0.x

Upgrade the modules as usual (Apps > the module > Upgrade). Two things are deliberately left as they are:

- The text of the two customer e-mails (quotation follow-up, overdue invoice reminder) is kept, in case you adapted it. To get the new wording: Settings > Technical > Email > Email Templates, open the template, then click Reset Template.
- The automatic reminders go on as before for the quotations and invoices already being chased. They now have a start date in the settings of Sales and Invoicing: on a new installation it is the day of the installation, so that old quotations and old unpaid invoices are not chased by surprise; after an upgrade it stays empty, which means no limit. Set a date there if you want to stop chasing older documents.

## Languages

English and French (`i18n/fr.po` in each module that has text to translate). The e-mails sent to your customers (quotation follow-up, overdue invoice reminder) are in French for customers whose language is French, in English otherwise.

## Need one adapted to your company?

I adapt these modules to the way you work, or build the small Odoo feature you are missing. Fixed price announced before I start, paid on delivery.

Contact: alexandre@alexandregabriel.ch, https://alexandregabriel.ch/?v=odoo

En français : décrivez votre besoin en deux lignes, je vous réponds avec un prix fixe sous 24 h.
