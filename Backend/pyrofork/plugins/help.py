from pyrogram import Client, filters
from pyrogram.types import Message
from Backend.config import Telegram
from Backend.helper.custom_filter import CustomFilters

@Client.on_message(filters.command("help"))
async def help_command(client: Client, message: Message):
    if Telegram.SUBSCRIPTION:
        text = (
            "<b>Bot Komutları:</b>\n\n"
            "/start - Ana menü / Üyelik satın al\n"
            "/status - Abonelik durumunu ve bitiş tarihini kontrol et\n"
            "/help - Bu yardım mesajını göster"
        )
    else:
        text = (
            "<b>Bot Komutları:</b>\n\n"
            "/start - Stremio Eklenti bağlantısını al\n"
            "/help - Bu yardım mesajını göster"
        )
        
    await message.reply_text(text, quote=True)
