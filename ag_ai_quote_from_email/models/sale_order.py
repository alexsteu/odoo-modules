import json
import logging
import re

import requests

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

DEFAULT_MODELS = {"anthropic": "claude-haiku-5-5", "openai": "gpt-4o-mini"}
MAX_PRODUCTS = 600

PROMPT = """You turn a customer e-mail into a sales quotation for a company using Odoo.
Return ONLY a JSON object, no other text, with this shape:
{"customer": {"name": str|null, "company": str|null, "email": str|null, "phone": str|null},
 "lines": [{"product_id": int|null, "description": str, "quantity": number}],
 "note": str|null}
Rules:
- Use only product_id values from the catalogue below. If the customer asks for something that is not in it, use null and describe it.
- quantity defaults to 1 when not stated.
- note: delivery date, address or other request worth keeping, in the language of the e-mail.
Catalogue (id | internal reference | name):
%s
"""


class SaleOrder(models.Model):
    _inherit = "sale.order"

    @api.model
    def _ag_ai_catalogue(self):
        products = self.env["product.product"].search(
            [("sale_ok", "=", True)], limit=MAX_PRODUCTS, order="id desc"
        )
        return "\n".join(f"{p.id} | {p.default_code or ''} | {p.name}" for p in products)

    @api.model
    def _ag_ai_call(self, system, text):
        """Return the raw text answer of the configured AI provider."""
        icp = self.env["ir.config_parameter"].sudo()
        provider = icp.get_param("ag_ai_quote.provider") or "anthropic"
        key = icp.get_param("ag_ai_quote.api_key")
        if not key:
            raise UserError(_("Add your AI API key in Sales > Configuration > Settings > AI quotation."))
        model = icp.get_param("ag_ai_quote.model") or DEFAULT_MODELS[provider]
        try:
            if provider == "openai":
                resp = requests.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json={"model": model, "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": text},
                    ], "response_format": {"type": "json_object"}},
                    timeout=90,
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                json={"model": model, "max_tokens": 4096, "system": system,
                      "messages": [{"role": "user", "content": text}]},
                timeout=90,
            )
            resp.raise_for_status()
            return "".join(b.get("text", "") for b in resp.json()["content"])
        except requests.RequestException as e:
            detail = getattr(e.response, "text", "") if getattr(e, "response", None) is not None else str(e)
            _logger.warning("AI quotation call failed: %s", detail)
            raise UserError(_("The AI service did not answer: %s", detail[:300])) from e

    @api.model
    def _ag_ai_parse(self, email_text):
        raw = self._ag_ai_call(PROMPT % self._ag_ai_catalogue(), email_text)
        match = re.search(r"\{.*\}", raw or "", re.S)
        try:
            return json.loads(match.group(0)) if match else {}
        except ValueError:
            raise UserError(_("The AI answer could not be read. Please try again.")) from None

    @api.model
    def _ag_ai_find_partner(self, customer):
        Partner = self.env["res.partner"]
        email = (customer.get("email") or "").strip()
        if email:
            partner = Partner.search([("email", "=ilike", email)], limit=1)
            if partner:
                return partner
        for name in (customer.get("company"), customer.get("name")):
            if name:
                partner = Partner.search([("name", "=ilike", name.strip())], limit=1)
                if partner:
                    return partner
        name = customer.get("company") or customer.get("name") or email
        if not name:
            return Partner
        company = Partner.create({"name": customer["company"], "is_company": True}) if customer.get("company") else Partner
        return Partner.create({
            "name": customer.get("name") or name,
            "email": email or False,
            "phone": customer.get("phone") or False,
            "parent_id": company.id or False,
        }) if customer.get("name") or email else company

    def _ag_ai_apply(self, data):
        self.ensure_one()
        Product = self.env["product.product"]
        lines, missing = [], []
        for item in data.get("lines") or []:
            try:
                qty = float(item.get("quantity") or 1)
            except (TypeError, ValueError):
                qty = 1.0
            product = Product.browse(item["product_id"]).exists() if isinstance(item.get("product_id"), int) else Product
            if product and product.sale_ok:
                lines.append((0, 0, {"product_id": product.id, "product_uom_qty": qty}))
            elif item.get("description"):
                missing.append(f"{qty:g} x {item['description']}")
        if missing:
            lines.append((0, 0, {"display_type": "line_note",
                                 "name": _("Not found in your products, to check: %s", "; ".join(missing))}))
        vals = {"order_line": lines}
        if data.get("note"):
            vals["note"] = data["note"]
        self.write(vals)
        return {"added": len(lines) - (1 if missing else 0), "missing": len(missing)}
