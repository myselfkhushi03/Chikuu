"""⌨️ Saare inline keyboards."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💻 Code se banao",  callback_data="mode_code")],
        [InlineKeyboardButton("📁 Files se banao", callback_data="mode_files")],
        [InlineKeyboardButton("📝 Details se banao", callback_data="mode_details")],
        [
            InlineKeyboardButton("📊 Status", callback_data="status"),
            InlineKeyboardButton("🗑️ Reset",  callback_data="reset"),
        ],
    ])


def after_generate_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬇️ ZIP",     callback_data="dl_zip"),
            InlineKeyboardButton("⬇️ HTML",    callback_data="dl_html"),
        ],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="home")],
    ])


def layout_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Hero Landing",  callback_data="layout_hero")],
        [InlineKeyboardButton("Portfolio",     callback_data="layout_portfolio")],
        [InlineKeyboardButton("Blog",          callback_data="layout_blog")],
        [InlineKeyboardButton("Product Card",  callback_data="layout_card")],
        [InlineKeyboardButton("❌ Cancel",     callback_data="home")],
    ])


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Back", callback_data="home")]
    ])
