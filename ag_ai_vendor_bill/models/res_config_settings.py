from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    ag_ai_bill_provider = fields.Selection(
        [("anthropic", "Claude (Anthropic)"), ("openai", "ChatGPT (OpenAI)")],
        string="AI provider", default="anthropic", config_parameter="ag_ai_bill.provider",
    )
    ag_ai_bill_api_key = fields.Char(string="AI API key", config_parameter="ag_ai_bill.api_key")
    ag_ai_bill_model = fields.Char(
        string="AI model", config_parameter="ag_ai_bill.model",
        help="Leave empty for the default: claude-sonnet-5-5 (Claude) or gpt-4o (ChatGPT).",
    )
