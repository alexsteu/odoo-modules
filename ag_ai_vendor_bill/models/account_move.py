import json
import logging
import re
import threading
import time
import unicodedata

import requests

from odoo import _, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare
from odoo.tools.misc import formatLang

_logger = logging.getLogger(__name__)

DEFAULT_MODELS = {"anthropic": "claude-sonnet-5-5", "openai": "gpt-4o"}
SUPPORTED = {"application/pdf", "image/png", "image/jpeg", "image/webp"}
# Ceiling of the answer (the provider only bills what is really written)
MAX_TOKENS = 16000
# One bill: seconds left to the AI to answer. Odoo stops a request after 120 seconds by default.
CALL_TIMEOUT = 100
# Several bills in one action: no new bill is started after BATCH_TIME_BUDGET seconds,
# so that the longest case (budget + one call) still ends before Odoo stops the request.
BATCH_CALL_TIMEOUT = 60
BATCH_TIME_BUDGET = 45
# Words that do not help to recognise a vendor ("Papeterie du Lac" is "PAPETERIE DU LAC SA")
LEGAL_FORMS = {
    "sa", "sarl", "sas", "sasu", "eurl", "snc", "sci", "scop", "gmbh", "ag", "kg", "ohg", "ug", "se",
    "sprl", "srl", "bv", "nv", "ltd", "limited", "inc", "llc", "plc", "spa", "sl", "co", "cie",
}

PROMPT = """Read this supplier invoice and return ONLY a JSON object, no other text:
{"vendor": {"name": str, "vat": str|null, "email": str|null, "street": str|null, "zip": str|null, "city": str|null, "country": "ISO 3166-1 alpha-2 code"|null},
 "invoice_number": str|null, "invoice_date": "YYYY-MM-DD"|null, "due_date": "YYYY-MM-DD"|null,
 "currency": "ISO code"|null,
 "lines": [{"description": str, "quantity": number, "unit_price": number, "tax_percent": number|null}],
 "total_untaxed": number|null, "total": number|null}
Rules: the vendor is the company that ISSUED the invoice, never the company that receives it. unit_price is WITHOUT tax. If the invoice only shows tax-included amounts, convert them. One line per invoice line; if there are no detailed lines, one line with the total without tax."""


def _ilike_escape(text):
    """`_` and `%` are wildcards for (i)like: escape them to compare a value as it is written."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _vat_key(vat):
    """BE 0477.472.701 and be0477472701 are the same number; so are CHE-123.456.789 TVA and MWST."""
    key = re.sub(r"[^A-Z0-9]", "", (vat or "").upper())
    return re.sub(r"(MWST|TVA|IVA|VAT)$", "", key)


def _name_key(name):
    """Return (name without accents, punctuation and legal form; legal forms found in it)."""
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    text = re.sub(r"\b([a-z])\.", r"\1", text)  # S.A. -> SA
    words = re.findall(r"[a-z0-9]+", text)
    kept = [word for word in words if word not in LEGAL_FORMS]
    return " ".join(kept or words), {word for word in words if word in LEGAL_FORMS} if kept else set()


def _same_vendor_name(name, other):
    """Same name once the legal form is set aside; two different legal forms are two companies."""
    key, forms = _name_key(name)
    other_key, other_forms = _name_key(other)
    return bool(key) and key == other_key and (not forms or not other_forms or forms == other_forms)


def _stop_error(message):
    """Error that will be the same for every bill (key missing or refused): no need to try the next ones."""
    error = UserError(message)
    error.ag_ai_stop = True
    return error


class AccountMove(models.Model):
    _inherit = "account.move"

    ag_ai_read = fields.Boolean(string="Read by AI", copy=False, readonly=True)

    def _ag_ai_bill_attachment(self):
        self.ensure_one()
        atts = self.env["ir.attachment"].search([
            ("res_model", "=", "account.move"), ("res_id", "=", self.id),
            ("mimetype", "in", list(SUPPORTED)),
        ], order="id desc")
        main = self.message_main_attachment_id if "message_main_attachment_id" in self._fields else False
        return main if main and main.mimetype in SUPPORTED else atts[:1]

    # ------------------------------------------------------------------ call to the AI provider
    def _ag_ai_bill_request(self, url, headers, payload, timeout):
        """POST to the AI provider; errors are turned into messages an accountant can act on."""
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.Timeout as error:
            raise UserError(_("The AI service did not answer in time. Please try again.")) from error
        except requests.RequestException as error:
            response = getattr(error, "response", None)
            status = getattr(response, "status_code", None)
            detail = ""
            if response is not None:
                try:
                    detail = ((response.json() or {}).get("error") or {}).get("message") or ""
                except (ValueError, AttributeError):
                    detail = ""
            _logger.warning("AI bill reading failed (HTTP %s): %s", status, detail or error)
            if status in (401, 403):
                raise _stop_error(_(
                    "The AI provider refused your API key. Check it in Accounting > Configuration > Settings > AI bill reader."
                )) from error
            if status == 429:
                raise UserError(_(
                    "The AI provider is limiting your account (too many requests or no credit left). "
                    "Try again in a minute or check your account with the provider."
                )) from error
            if status and status >= 500:
                raise UserError(_("The AI service is temporarily overloaded. Please try again in a minute.")) from error
            raise UserError(_("The AI service did not answer: %s", detail or _("connection error"))) from error
        except ValueError as error:
            raise UserError(_("The AI answer could not be read. Please try again.")) from error

    def _ag_ai_bill_call(self, attachment, timeout=CALL_TIMEOUT):
        """Return the raw text answer of the configured AI provider for this document."""
        icp = self.env["ir.config_parameter"].sudo()
        provider = icp.get_param("ag_ai_bill.provider") or icp.get_param("ag_ai_quote.provider") or "anthropic"
        key = icp.get_param("ag_ai_bill.api_key") or icp.get_param("ag_ai_quote.api_key")
        if not key:
            raise _stop_error(_("Add your AI API key in Accounting > Configuration > Settings > AI bill reader."))
        model = icp.get_param("ag_ai_bill.model") or DEFAULT_MODELS[provider]
        data = attachment.datas.decode() if isinstance(attachment.datas, bytes) else attachment.datas
        mime = attachment.mimetype
        if provider == "openai":
            part = ({"type": "file", "file": {"filename": attachment.name or "invoice.pdf",
                                              "file_data": f"data:{mime};base64,{data}"}}
                    if mime == "application/pdf" else
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}})
            answer = self._ag_ai_bill_request(
                "https://api.openai.com/v1/chat/completions",
                {"Authorization": f"Bearer {key}"},
                {"model": model, "response_format": {"type": "json_object"},
                 "messages": [{"role": "user", "content": [part, {"type": "text", "text": PROMPT}]}]},
                timeout,
            )
            choice = (answer.get("choices") or [{}])[0]
            if choice.get("finish_reason") == "length":
                raise UserError(_("The AI answer is too long and was cut. This document has too many lines for one reading."))
            return (choice.get("message") or {}).get("content") or ""
        # the document comes first, the instructions after it
        block = {"type": "document" if mime == "application/pdf" else "image",
                 "source": {"type": "base64", "media_type": mime, "data": data}}
        answer = self._ag_ai_bill_request(
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": key, "anthropic-version": "2023-06-01"},
            {"model": model, "max_tokens": MAX_TOKENS,
             "messages": [{"role": "user", "content": [block, {"type": "text", "text": PROMPT}]}]},
            timeout,
        )
        # always read the stop reason before the content
        stop_reason = answer.get("stop_reason")
        if stop_reason == "refusal":
            raise UserError(_("The AI declined to read this document. Please fill the bill by hand."))
        if stop_reason == "max_tokens":
            raise UserError(_("The AI answer is too long and was cut. This document has too many lines for one reading."))
        return "".join(
            part.get("text", "") for part in answer.get("content") or [] if part.get("type") == "text"
        )

    def _ag_ai_bill_parse(self, raw):
        raw = raw or ""
        start, end = raw.find("{"), raw.rfind("}")
        try:
            data = json.loads(raw[start:end + 1]) if start != -1 and end > start else None
        except ValueError:
            data = None
        if not isinstance(data, dict):
            raise UserError(_("The AI answer could not be read. Please try again."))
        return data

    # ------------------------------------------------------------------ result into Odoo
    def _ag_ai_bill_partner_by_vat(self, vat):
        key = _vat_key(vat)
        if len(key) < 6:
            return self.env["res.partner"]
        Partner = self.env["res.partner"]
        Partner.flush_model(["vat"])
        normalized = "regexp_replace(regexp_replace(upper(vat), '[^A-Z0-9]', '', 'g'), '(MWST|TVA|IVA|VAT)$', '')"
        self.env.cr.execute(
            f"SELECT id FROM res_partner WHERE vat IS NOT NULL AND {normalized} = %s", [key]
        )
        ids = [row[0] for row in self.env.cr.fetchall()]
        if not ids and key.isdigit() and len(key) >= 8:
            # number printed without its country letters: BE0477472701 is stored, 0477472701 is printed
            self.env.cr.execute(
                f"SELECT id FROM res_partner WHERE vat IS NOT NULL AND {normalized} ~ %s", ["^[A-Z]{2}" + key + "$"]
            )
            ids = [row[0] for row in self.env.cr.fetchall()]
        # the search applies the access rules and the companies of the user
        return Partner.search([("id", "in", ids)], order="is_company desc, id", limit=1).commercial_partner_id

    def _ag_ai_bill_partner_by_name(self, name):
        Partner = self.env["res.partner"]
        partner = Partner.search([("name", "=ilike", _ilike_escape(name))], order="is_company desc, id", limit=1)
        if partner:
            return partner
        # same vendor written with or without its legal form: "Papeterie du Lac" and "PAPETERIE DU LAC SA"
        words = [word for word in re.findall(r"\w+", name.lower()) if len(word) >= 3 and word not in LEGAL_FORMS]
        if not words:
            return Partner
        word = max(words, key=lambda candidate: (candidate.isascii(), len(candidate)))
        candidates = Partner.search(
            [("name", "ilike", word), ("parent_id", "=", False)], order="is_company desc, id", limit=200
        )
        return candidates.filtered(lambda candidate: _same_vendor_name(name, candidate.name))[:1]

    def _ag_ai_bill_partner(self, vendor, remarks=None):
        """Vendor of the bill: by tax ID, then by name; created when unknown."""
        remarks = remarks if remarks is not None else []
        Partner = self.env["res.partner"]
        partner = self._ag_ai_bill_partner_by_vat(vendor.get("vat"))
        if partner:
            return partner
        name = (vendor.get("name") or "").strip()
        if not name:
            return Partner
        partner = self._ag_ai_bill_partner_by_name(name)
        if partner:
            return partner
        country = Partner.country_id
        if isinstance(vendor.get("country"), str) and len(vendor["country"].strip()) == 2:
            country = self.env["res.country"].search([("code", "=", vendor["country"].strip().upper())], limit=1)
        vals = {
            "name": name, "is_company": True, "vat": vendor.get("vat") or False,
            "email": vendor.get("email") or False, "street": vendor.get("street") or False,
            "zip": vendor.get("zip") or False, "city": vendor.get("city") or False,
            "country_id": country.id or False,
        }
        try:
            with self.env.cr.savepoint():
                return Partner.create(vals)
        except ValidationError:
            # a tax ID that Odoo does not accept (misread, or unusual format) must not block the bill
            remarks.append(_("Tax ID read on the document: %s. Odoo did not accept it, so it was left empty on the new vendor.",
                             vals.pop("vat")))
            return Partner.create(vals)

    def _ag_ai_bill_tax(self, percent):
        Tax = self.env["account.tax"]
        if percent in (None, ""):
            return Tax
        try:
            percent = float(percent)
        except (TypeError, ValueError):
            return Tax
        taxes = Tax.search([
            *Tax._check_company_domain(self.company_id),
            ("type_tax_use", "=", "purchase"), ("amount_type", "=", "percent"), ("price_include", "=", False),
        ])
        taxes = taxes.filtered(lambda tax: float_compare(tax.amount, percent, precision_digits=2) == 0)
        # several taxes with that rate: the default purchase tax of the company first
        default = self.company_id.account_purchase_tax_id
        return default if default in taxes else taxes[:1]

    def _ag_ai_bill_apply(self, data):
        self.ensure_one()
        vals, remarks = {}, []
        vendor = data.get("vendor") if isinstance(data.get("vendor"), dict) else {}
        if not self.partner_id:
            partner = self._ag_ai_bill_partner(vendor, remarks)
            if partner:
                vals["partner_id"] = partner.id
        if data.get("invoice_number"):
            vals["ref"] = str(data["invoice_number"])
        for key, field in (("invoice_date", "invoice_date"), ("due_date", "invoice_date_due")):
            try:
                if data.get(key):
                    vals[field] = fields.Date.to_date(data[key])
            except (TypeError, ValueError):
                pass
        if isinstance(data.get("currency"), str) and data["currency"].strip():
            code = data["currency"].strip().upper()
            currency = self.env["res.currency"].with_context(active_test=False).search([("name", "=", code)], limit=1)
            if currency.active:
                vals["currency_id"] = currency.id
            elif code != self.currency_id.name:
                remarks.append(_(
                    "The document is in %(currency)s, a currency that is not active in Odoo: the bill stays in %(kept)s.",
                    currency=code, kept=self.currency_id.name,
                ))
        lines = []
        for item in data.get("lines") or []:
            if not isinstance(item, dict):
                continue
            try:
                qty = float(item.get("quantity") or 1)
                price = float(item.get("unit_price") or 0)
            except (TypeError, ValueError):
                continue
            tax = self._ag_ai_bill_tax(item.get("tax_percent"))
            lines.append((0, 0, {
                "name": str(item.get("description") or "/"), "quantity": qty, "price_unit": price,
                "tax_ids": [(6, 0, tax.ids)],
            }))
        if lines:
            vals["invoice_line_ids"] = [(5, 0, 0)] + lines
        else:
            remarks.append(_("No line could be read on the document."))
        vals["ag_ai_read"] = True
        self.write(vals)
        message = _("Bill filled by AI from %s. Please check it before posting.", self._ag_ai_bill_attachment().name)
        total = data.get("total")
        if isinstance(total, (int, float)) and not isinstance(total, bool) \
                and self.currency_id.compare_amounts(self.amount_total, total) != 0:
            remarks.append(_(
                "Warning: total on the document %(doc)s, total in Odoo %(odoo)s (check the taxes).",
                doc=formatLang(self.env, total, currency_obj=self.currency_id),
                odoo=formatLang(self.env, self.amount_total, currency_obj=self.currency_id),
            ))
        self.message_post(body=" ".join([message] + remarks))

    def _ag_ai_read_one(self, timeout=CALL_TIMEOUT):
        """Read the document attached to this bill and fill the bill. Raises UserError with the reason."""
        self.ensure_one()
        attachment = self._ag_ai_bill_attachment()
        if not attachment:
            raise UserError(_("no PDF or image attached. Attach the supplier invoice to the bill, then try again."))
        self._ag_ai_bill_apply(self._ag_ai_bill_parse(self._ag_ai_bill_call(attachment, timeout)))

    def action_ag_ai_read_bill(self):
        bills = self.filtered(lambda move: move.move_type in ("in_invoice", "in_refund") and move.state == "draft")
        if not bills:
            raise UserError(_("Select draft vendor bills."))
        several = len(bills) > 1
        # outside of the tests, each bill is saved as soon as it is read: what was paid to the AI is never lost
        auto_commit = several and not getattr(threading.current_thread(), "testing", False)
        started = time.monotonic()
        done, failed, waiting = 0, [], 0
        for position, bill in enumerate(bills):
            if several and time.monotonic() - started > BATCH_TIME_BUDGET:
                waiting = len(bills) - position
                break
            try:
                with self.env.cr.savepoint():
                    bill._ag_ai_read_one(BATCH_CALL_TIMEOUT if several else CALL_TIMEOUT)
                done += 1
            except UserError as error:
                stop = getattr(error, "ag_ai_stop", False)
                if stop and not done:
                    raise
                failed.append("%s: %s" % (bill.display_name, error.args[0]))
                if stop:
                    waiting = len(bills) - position - 1
                    break
            if auto_commit:
                self.env.cr.commit()
        if not several and not failed:
            return True
        parts = [_("%s bill(s) filled.", done)] if several or done else []
        parts += failed
        if waiting:
            parts.append(_("%s bill(s) not started: select them and run the action again.", waiting))
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "title": _("AI bill reader"),
            "message": " ".join(parts),
            "type": "warning" if failed or waiting else "success",
            "sticky": bool(failed or waiting),
            "next": {"type": "ir.actions.client", "tag": "soft_reload"},
        }}
