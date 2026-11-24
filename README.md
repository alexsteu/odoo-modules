# Free Odoo 18 modules for SMEs

By Alexandre Gabriel, independent Odoo developer. Tested on Odoo 18 (Community).

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

Every module comes with automated tests (181 in total on this branch). To run the tests of one module on a test database:

    odoo-bin -d <test database> -i <module> --test-tags /<module> --stop-after-init

The two AI modules are tested with simulated answers of the AI providers: the tests never call a paid service.

## Upgrading from version 18.0.1.0.x

Replace the code, then upgrade on the command line, before anyone signs in, all the modules of this suite that are installed, in one go:

    odoo-bin -d <database> -u <module>,<module> --stop-after-init

Three modules (`ag_invoice_vat_required`, `ag_invoice_overdue_reminder`, `ag_sale_quote_followup`) add fields to contacts and companies. Until they are upgraded, Odoo refuses the sign-in, so the Upgrade button of the Apps screen cannot be used. Tried on Odoo 18 Community, from 18.0.1.0.1 to 18.0.1.1.0, with the 18 modules installed. Not tried on Odoo.sh.

What changes for a database that already runs these modules:

- Automatic reminders (quotation follow-up, overdue invoices). They now have a start date in the settings of Sales and Invoicing. On a new installation it is the day of the installation, so that old quotations and old unpaid invoices are not chased by surprise. After an upgrade, the reminders in progress go on: the date is left empty, which means no limit, in the companies where the reminders were switched on. Where they were switched off, the date is the day of the upgrade. Set a date there if you want to stop chasing older documents.
- Text of the two customer e-mails. The text you may have rewritten is kept. This version adds a French text: if French is active in your database and you had rewritten the text in English only, your French-speaking customers now receive the standard French text. Review the French version of the template (Settings > Technical > Email > Email Templates). To get the new English wording, open the template and click Reset Template.
- `ag_invoice_vat_required`: the check now also applies to the list action and to the invoices Odoo posts by itself. Before, only the Confirm button of the invoice was covered. The box "No Tax ID needed" on the contact is new.
- `ag_project_profitability`: the figures are reserved to project managers in every case, and the Project settings get the box Analytic Accounting.

## Languages

English and French (`i18n/fr.po` in each module that has text to translate). The e-mails sent to your customers (quotation follow-up, overdue invoice reminder) are in French for customers whose language is French, in English otherwise.

## Need one adapted to your company?

I adapt these modules to the way you work, or build the small Odoo feature you are missing. Fixed price announced before I start, paid on delivery. I answer within one working day, with that price or with the question I still need to set it.

Contact: alexandre@alexandregabriel.ch, https://alexandregabriel.ch/?v=odoo

En français : décrivez votre besoin en deux lignes. Je vous réponds sous un jour ouvré, avec un prix fixe ou la question qui me manque pour le fixer.
