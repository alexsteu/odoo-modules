import json
import logging
import re

import requests

from odoo import _, api, models, tools
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

DEFAULT_MODELS = {"anthropic": "claude-haiku-5-5", "openai": "gpt-4o-mini"}
# Products listed to the AI. Above this number, the ones the e-mail talks about come first.
MAX_PRODUCTS = 600
# Words of the e-mail looked up in the catalogue (longest first) when it is larger than the limit
MAX_WORDS = 150
# Ceiling of the answer (the provider only bills what is really written)
MAX_TOKENS = 16000

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


def _ilike_escape(text):
    """`_` and `%` are wildcards for (i)like: escape them to compare a value as it is written."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class SaleOrder(models.Model):
    _inherit = "sale.order"

    # ------------------------------------------------------------------ catalogue sent to the AI
    @api.model
    def _ag_ai_catalogue(self, email_text=""):
        Product = self.env["product.product"]
        domain = [("sale_ok", "=", True)]
        products = Product.search(domain, limit=MAX_PRODUCTS + 1, order="id desc")
        if len(products) > MAX_PRODUCTS:
            products = self._ag_ai_relevant_products(email_text, domain)
        return "\n".join(f"{p.id} | {p.default_code or ''} | {p.name}" for p in products)

    @api.model
    def _ag_ai_relevant_products(self, email_text, domain):
        """Catalogue larger than the limit: keep first the products the e-mail talks about.

        A product is relevant when its name or reference contains a word of the e-mail
        ("chairs" also finds "chair", "CH-01" is read as one reference). A word found in
        more products than the limit does not help to choose and is ignored. The rest of
        the list is filled with the newest products.
        """
        Product = self.env["product.product"]
        text = (email_text or "").lower()
        words = set(re.findall(r"\w{4,}", text))
        words |= {word[:-1] for word in words if word[-1] in "sx" and len(word) > 4}
        words |= {ref for ref in re.findall(r"\w+(?:[-./]\w+)+", text) if any(char.isdigit() for char in ref)}
        scores = {}
        for word in sorted(words, key=len, reverse=True)[:MAX_WORDS]:
            found = Product.search(
                domain + ["|", ("name", "ilike", word), ("default_code", "ilike", word)], limit=MAX_PRODUCTS + 1
            )
            if len(found) > MAX_PRODUCTS:
                continue
            for product_id in found.ids:
                scores[product_id] = scores.get(product_id, 0) + 1
        best = sorted(scores, key=lambda product_id: (-scores[product_id], -product_id))[:MAX_PRODUCTS]
        matched = Product.browse(best)
        recent = Product
        if len(matched) < MAX_PRODUCTS:
            recent = Product.search(
                domain + [("id", "not in", matched.ids)], limit=MAX_PRODUCTS - len(matched), order="id desc"
            )
        return matched | recent

    # ------------------------------------------------------------------ call to the AI provider
    @api.model
    def _ag_ai_request(self, url, headers, payload, timeout=90):
        """POST to the AI provider; errors are turned into messages a salesperson can act on."""
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
            _logger.warning("AI quotation call failed (HTTP %s): %s", status, detail or error)
            if status in (401, 403):
                raise UserError(_(
                    "The AI provider refused your API key. Check it in Sales > Configuration > Settings > AI quotation."
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

    @api.model
    def _ag_ai_call(self, system, text):
        """Return the raw text answer of the configured AI provider."""
        icp = self.env["ir.config_parameter"].sudo()
        provider = icp.get_param("ag_ai_quote.provider") or "anthropic"
        key = icp.get_param("ag_ai_quote.api_key")
        if not key:
            raise UserError(_("Add your AI API key in Sales > Configuration > Settings > AI quotation."))
        model = icp.get_param("ag_ai_quote.model") or DEFAULT_MODELS[provider]
        if provider == "openai":
            data = self._ag_ai_request(
                "https://api.openai.com/v1/chat/completions",
                {"Authorization": f"Bearer {key}"},
                {"model": model, "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": text},
                ], "response_format": {"type": "json_object"}},
            )
            choice = (data.get("choices") or [{}])[0]
            if choice.get("finish_reason") == "length":
                raise UserError(_("The AI answer is too long and was cut. Try with a shorter e-mail."))
            return (choice.get("message") or {}).get("content") or ""
        data = self._ag_ai_request(
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": key, "anthropic-version": "2023-06-01"},
            {"model": model, "max_tokens": MAX_TOKENS, "system": system,
             "messages": [{"role": "user", "content": text}]},
        )
        # always read the stop reason before the content
        stop_reason = data.get("stop_reason")
        if stop_reason == "refusal":
            raise UserError(_("The AI declined to process this e-mail. Please fill the quotation by hand."))
        if stop_reason == "max_tokens":
            raise UserError(_("The AI answer is too long and was cut. Try with a shorter e-mail."))
        return "".join(
            block.get("text", "") for block in data.get("content") or [] if block.get("type") == "text"
        )

    @api.model
    def _ag_ai_parse(self, email_text):
        raw = self._ag_ai_call(PROMPT % self._ag_ai_catalogue(email_text), email_text) or ""
        start, end = raw.find("{"), raw.rfind("}")
        try:
            data = json.loads(raw[start:end + 1]) if start != -1 and end > start else None
        except ValueError:
            data = None
        if not isinstance(data, dict):
            raise UserError(_("The AI answer could not be read. Please try again."))
        return data

    # ------------------------------------------------------------------ result into Odoo
    @api.model
    def _ag_ai_find_partner(self, customer):
        Partner = self.env["res.partner"]
        email = (customer.get("email") or "").strip()
        normalized = tools.email_normalize(email) if email else False
        if normalized:
            partner = Partner.search([("email_normalized", "=", normalized)], limit=1)
            if partner:
                return partner
        company_name = (customer.get("company") or "").strip()
        person_name = (customer.get("name") or "").strip()
        for name in (company_name, person_name):
            if name:
                partner = Partner.search([("name", "=ilike", _ilike_escape(name))], limit=1)
                if partner:
                    return partner
        if not (company_name or person_name or email):
            return Partner
        company = Partner.create({"name": company_name, "is_company": True}) if company_name else Partner
        if not (person_name or email):
            return company
        return Partner.create({
            "name": person_name or email,
            "email": email or False,
            "phone": customer.get("phone") or False,
            "parent_id": company.id or False,
        })

    def _ag_ai_apply(self, data):
        self.ensure_one()
        Product = self.env["product.product"]
        lines, missing = [], []
        for item in data.get("lines") or []:
            if not isinstance(item, dict):
                continue
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
            # added after the terms already written on the quotation, never instead of them
            request = tools.plaintext2html(str(data["note"]))
            vals["note"] = request if tools.is_html_empty(self.note) else self.note + request
        self.write(vals)
        return {"added": len(lines) - (1 if missing else 0), "missing": len(missing)}
