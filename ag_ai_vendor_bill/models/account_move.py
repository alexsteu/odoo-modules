import base64
import json
import logging
import re

import requests

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)

DEFAULT_MODELS = {"anthropic": "claude-sonnet-5-5", "openai": "gpt-4o"}
SUPPORTED = {"application/pdf", "image/png", "image/jpeg", "image/webp"}

PROMPT = """Read this supplier invoice and return ONLY a JSON object, no other text:
{"vendor": {"name": str, "vat": str|null, "email": str|null, "street": str|null, "zip": str|null, "city": str|null},
 "invoice_number": str|null, "invoice_date": "YYYY-MM-DD"|null, "due_date": "YYYY-MM-DD"|null,
 "currency": "ISO code"|null,
 "lines": [{"description": str, "quantity": number, "unit_price": number, "tax_percent": number|null}],
 "total_untaxed": number|null, "total": number|null}
Rules: unit_price is WITHOUT tax. If the invoice only shows tax-included amounts, convert them. One line per invoice line; if there are no detailed lines, one line with the total without tax."""


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

    def _ag_ai_bill_call(self, attachment):
        icp = self.env["ir.config_parameter"].sudo()
        provider = icp.get_param("ag_ai_bill.provider") or icp.get_param("ag_ai_quote.provider") or "anthropic"
        key = icp.get_param("ag_ai_bill.api_key") or icp.get_param("ag_ai_quote.api_key")
        if not key:
            raise UserError(_("Add your AI API key in Accounting > Configuration > Settings > Vendor Bills > AI bill reader."))
        model = icp.get_param("ag_ai_bill.model") or DEFAULT_MODELS[provider]
        data = attachment.datas.decode() if isinstance(attachment.datas, bytes) else attachment.datas
        mime = attachment.mimetype
        try:
            if provider == "openai":
                part = ({"type": "file", "file": {"filename": attachment.name or "invoice.pdf",
                                                  "file_data": f"data:{mime};base64,{data}"}}
                        if mime == "application/pdf" else
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}})
                resp = requests.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json={"model": model, "response_format": {"type": "json_object"},
                          "messages": [{"role": "user", "content": [part, {"type": "text", "text": PROMPT}]}]},
                    timeout=120,
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            block = {"type": "document" if mime == "application/pdf" else "image",
                     "source": {"type": "base64", "media_type": mime, "data": data}}
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                json={"model": model, "max_tokens": 4096,
                      "messages": [{"role": "user", "content": [block, {"type": "text", "text": PROMPT}]}]},
                timeout=120,
            )
            resp.raise_for_status()
            return "".join(b.get("text", "") for b in resp.json()["content"])
        except requests.RequestException as e:
            detail = e.response.text if getattr(e, "response", None) is not None else str(e)
            _logger.warning("AI bill reading failed: %s", detail)
            raise UserError(_("The AI service did not answer: %s", detail[:300])) from e

    def _ag_ai_bill_partner(self, vendor):
        Partner = self.env["res.partner"]
        vat = re.sub(r"[^A-Za-z0-9]", "", vendor.get("vat") or "").upper()
        if vat:
            for p in Partner.search([("vat", "!=", False), ("is_company", "=", True)]):
                if re.sub(r"[^A-Za-z0-9]", "", p.vat).upper() == vat:
                    return p
        name = (vendor.get("name") or "").strip()
        if not name:
            return Partner
        partner = Partner.search([("name", "=ilike", name)], limit=1)
        if partner:
            return partner
        return Partner.create({
            "name": name, "is_company": True, "vat": vendor.get("vat") or False,
            "email": vendor.get("email") or False, "street": vendor.get("street") or False,
            "zip": vendor.get("zip") or False, "city": vendor.get("city") or False,
        })

    def _ag_ai_bill_tax(self, percent):
        if percent in (None, ""):
            return self.env["account.tax"]
        try:
            percent = float(percent)
        except (TypeError, ValueError):
            return self.env["account.tax"]
        taxes = self.env["account.tax"].search([
            ("type_tax_use", "=", "purchase"), ("amount_type", "=", "percent"),
            ("company_id", "=", self.company_id.id), ("price_include", "=", False),
        ])
        return taxes.filtered(lambda t: float_compare(t.amount, percent, precision_digits=2) == 0)[:1]

    def _ag_ai_bill_apply(self, data):
        self.ensure_one()
        vals = {}
        partner = self._ag_ai_bill_partner(data.get("vendor") or {})
        if partner and not self.partner_id:
            vals["partner_id"] = partner.id
        if data.get("invoice_number"):
            vals["ref"] = data["invoice_number"]
        for key, field in (("invoice_date", "invoice_date"), ("due_date", "invoice_date_due")):
            try:
                if data.get(key):
                    vals[field] = fields.Date.to_date(data[key])
            except ValueError:
                pass
        if data.get("currency"):
            cur = self.env["res.currency"].with_context(active_test=False).search([("name", "=", data["currency"].upper())], limit=1)
            if cur:
                if not cur.active:
                    cur.active = True
                vals["currency_id"] = cur.id
        lines = []
        for item in data.get("lines") or []:
            try:
                qty = float(item.get("quantity") or 1)
                price = float(item.get("unit_price") or 0)
            except (TypeError, ValueError):
                continue
            tax = self._ag_ai_bill_tax(item.get("tax_percent"))
            line = {"name": item.get("description") or "/", "quantity": qty, "price_unit": price}
            line["tax_ids"] = [(6, 0, tax.ids)]
            lines.append((0, 0, line))
        if lines:
            vals["invoice_line_ids"] = [(5, 0, 0)] + lines
        vals["ag_ai_read"] = True
        self.write(vals)
        msg = _("Bill filled by AI from %s. Please check it before posting.", self._ag_ai_bill_attachment().name)
        total = data.get("total")
        if isinstance(total, (int, float)) and self.currency_id.compare_amounts(self.amount_total, total) != 0:
            msg += " " + _("Warning: total on the document %(doc)s, total in Odoo %(odoo)s (check the taxes).",
                           doc=total, odoo=self.amount_total)
        self.message_post(body=msg)

    def action_ag_ai_read_bill(self):
        bills = self.filtered(lambda m: m.move_type in ("in_invoice", "in_refund") and m.state == "draft")
        if not bills:
            raise UserError(_("Select draft vendor bills."))
        done, failed = 0, []
        for bill in bills:
            att = bill._ag_ai_bill_attachment()
            if not att:
                failed.append(_("%s: no PDF or image attached", bill.display_name))
                continue
            raw = bill._ag_ai_bill_call(att)
            match = re.search(r"\{.*\}", raw or "", re.S)
            try:
                data = json.loads(match.group(0)) if match else None
            except ValueError:
                data = None
            if not data:
                failed.append(_("%s: AI answer not readable", bill.display_name))
                continue
            bill._ag_ai_bill_apply(data)
            done += 1
        if len(bills) == 1 and not failed:
            return True
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "title": _("AI bill reader"),
            "message": _("%(done)s bill(s) filled. %(failed)s", done=done, failed=" ".join(failed)),
            "type": "warning" if failed else "success",
            "next": {"type": "ir.actions.client", "tag": "soft_reload"},
        }}
