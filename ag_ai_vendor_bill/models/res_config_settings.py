from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    # the labels name the bill reader: the AI quotation module has its own provider, key and model
    ag_ai_bill_provider = fields.Selection(
        [("anthropic", "Claude (Anthropic)"), ("openai", "ChatGPT (OpenAI)")],
        string="Bill reader: AI provider", default="anthropic", config_parameter="ag_ai_bill.provider",
    )
    ag_ai_bill_api_key = fields.Char(
        string="Bill reader: AI API key", config_parameter="ag_ai_bill.api_key",
        help="Key of your own account with the AI provider. Leave empty to use the key entered for "
             "AI quotations, when that module is installed.",
    )
    ag_ai_bill_model = fields.Char(
        string="Bill reader: AI model", config_parameter="ag_ai_bill.model",
        help="Leave empty for the default: claude-sonnet-5-5 (Claude) or gpt-4o (ChatGPT).",
    )
