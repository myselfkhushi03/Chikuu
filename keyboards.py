from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from config import ADMINS

def B(t,d=None,url=None): 
    return InlineKeyboardButton(text=t, url=url) if url else InlineKeyboardButton(text=t, callback_data=d)
def KB(*rows): return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows])

def reply_kb(uid):
    rows = [[KeyboardButton(text="➕ Create Website"), KeyboardButton(text="📂 My Websites")],
            [KeyboardButton(text="✏️ Edit by Code"), KeyboardButton(text="❓ Help")]]
    if uid in ADMINS: rows.append([KeyboardButton(text="🛠 Admin Panel")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)

def menu_kb(uid):
    rows = [[B("➕ Create Website","new")],[B("📂 My Websites","my"),B("✏️ Edit by Code","editcode")],[B("❓ Help","help")]]
    if uid in ADMINS: rows.append([B("🛠 Admin Panel","adm")])
    return KB(*rows)

cancel_kb = KB([B("✖️ Cancel","cancel")])