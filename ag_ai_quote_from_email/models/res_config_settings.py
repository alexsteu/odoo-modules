from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    ag_ai_provider = fields.Selection(
        [("anthropic", "Claude (Anthropic)"), ("openai", "ChatGPT (OpenAI)")],
        string="AI provider", default="anthropic", config_parameter="ag_ai_quote.provider",
    )
    ag_ai_api_key = fields.Char(string="AI API key", config_parameter="ag_ai_quote.api_key")
    ag_ai_model = fields.Char(
        string="AI model", config_parameter="ag_ai_quote.model",
        help="Leave empty for the default: claude-haiku-5-5 (Claude) or gpt-4o-mini (ChatGPT).",
    )
