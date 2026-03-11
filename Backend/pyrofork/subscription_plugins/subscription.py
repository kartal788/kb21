from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from Backend.config import Telegram
from Backend import db
from datetime import datetime, timedelta
import asyncio

@Client.on_callback_query(filters.regex(r"^plan_([a-fA-F0-9]{24})$"))
async def plan_selection(client: Client, callback_query: CallbackQuery):
    if not Telegram.SUBSCRIPTION:
        return await callback_query.answer("Abonelikler aktif değil.", show_alert=True)
        
    plan_id = callback_query.matches[0].group(1)
    plans = await db.get_subscription_plans()
    plan = next((p for p in plans if p["_id"] == plan_id), None)
    
    if not plan:
        return await callback_query.answer("Geçersiz plan.", show_alert=True)
        
    user_id = callback_query.from_user.id
    duration = plan["days"]
    price = plan["price"]

    # Yöneticiye gidecek mesaj
    admin_text = (
        f"<b>🔔 Yeni Abonelik Talebi!</b>\n\n"
        f"<b>👤 Kullanıcı:</b> {callback_query.from_user.mention}\n"
        f"<b>🆔 ID:</b> <code>{user_id}</code>\n"
        f"<b>📦 Plan:</b> {duration} Gün - {price} TL"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Onayla", callback_data=f"approve_{user_id}"),
            InlineKeyboardButton("❌ Reddet",  callback_data=f"reject_{user_id}")
        ]
    ])

    approver_ids = Telegram.APPROVER_IDS if Telegram.APPROVER_IDS else [Telegram.OWNER_ID]
    admin_messages = []
    
    for app_id in approver_ids:
        try:
            sent = await client.send_message(app_id, admin_text, reply_markup=keyboard)
            admin_messages.append({"chat_id": app_id, "message_id": sent.id})
        except Exception:
            pass

    # Veritabanına "bekliyor" olarak kaydet (Fotoğraf ID: 0)
    await db.set_pending_payment(user_id, int(duration), 0, price=price, admin_messages=admin_messages)

    # Kullanıcıya bilgi ver
    await callback_query.message.edit_text(
        "✅ <b>Talebiniz yöneticiye iletildi.</b>\n\n"
        "Onaylandığında size bilgi verilecektir. Lütfen bekleyin."
    )

@Client.on_callback_query(filters.regex(r"^(approve|reject)_(\d+)$"))
async def admin_review(client: Client, callback_query: CallbackQuery):
    approver_ids = Telegram.APPROVER_IDS if Telegram.APPROVER_IDS else [Telegram.OWNER_ID]
    if callback_query.from_user.id not in approver_ids:
        return await callback_query.answer("Yetkiniz yok.", show_alert=True)

    action = callback_query.matches[0].group(1)
    target_user_id = int(callback_query.matches[0].group(2))
    admin_name = callback_query.from_user.first_name

    user_pre = await db.get_user(target_user_id)
    if not user_pre or "pending_payment" not in user_pre:
        return await callback_query.answer("Bu talep zaten işlenmiş.", show_alert=True)

    admin_messages = user_pre["pending_payment"].get("admin_messages", [])
    duration = user_pre["pending_payment"].get("duration", "?")
    price = user_pre["pending_payment"].get("price", "?")

    if action == "approve":
        user_data = await db.approve_payment(target_user_id)
        if user_data:
            # Token ve Link oluşturma (mevcut mantık)
            token_doc = await db.add_api_token(name=str(target_user_id), user_id=target_user_id)
            addon_url = f"{Telegram.BASE_URL}/stremio/{token_doc.get('token')}/manifest.json"
            
            await client.send_message(
                target_user_id, 
                f"🎉 <b>Aboneliğiniz Onaylandı!</b>\n\n"
                f"Süre: {duration} Gün\n"
                f"Eklenti Linkiniz: <code>{addon_url}</code>"
            )
            status_text = f"✅ <b>{admin_name} onayladı.</b>\n\nID: {target_user_id}\nPlan: {duration} Gün"
        else:
            return await callback_query.answer("Hata oluştu.")

    else: # reject
        await db.reject_payment(target_user_id)
        await client.send_message(target_user_id, "❌ Abonelik talebiniz reddedildi.")
        status_text = f"❌ <b>{admin_name} reddetti.</b>\n\nID: {target_user_id}"

    # TÜM ADMİNLERDEKİ MESAJLARI GÜNCELLE (edit_text kullanarak)
    for am in admin_messages:
        try:
            await client.edit_message_text(
                chat_id=am["chat_id"],
                message_id=am["message_id"],
                text=status_text
            )
        except Exception:
            pass

@Client.on_callback_query(filters.regex(r"^cancel_payment$"))
async def cancel_payment_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id if callback_query.from_user else callback_query.message.chat.id
    
    # Remove pending payment
    await db.reject_payment(user_id)
    
    await callback_query.answer("Payment process cancelled.", show_alert=True)
    try:
        await callback_query.message.delete()
    except Exception:
        pass

@Client.on_callback_query(filters.regex(r"^(approve|reject)_(\d+)$"))
async def admin_review(client: Client, callback_query: CallbackQuery):
    approver_ids = Telegram.APPROVER_IDS if Telegram.APPROVER_IDS else [Telegram.OWNER_ID]
    if callback_query.from_user.id not in approver_ids:
        return await callback_query.answer("You are not authorized to perform this action.", show_alert=True)

    action = callback_query.matches[0].group(1)
    target_user_id = int(callback_query.matches[0].group(2))
    acting_admin = callback_query.from_user
    admin_name = acting_admin.first_name or acting_admin.username or f"Admin {acting_admin.id}"

    # Fetch admin_messages BEFORE any DB write (approve/reject unsets pending_payment)
    user_pre = await db.get_user(target_user_id)
    if not user_pre or "pending_payment" not in user_pre:
        return await callback_query.answer("This request has already been processed.", show_alert=True)

    admin_messages = user_pre["pending_payment"].get("admin_messages", [])

    if action == "approve":
        user_data = await db.approve_payment(target_user_id)
        if user_data:
            # Generate or retrieve existing API token for this user
            try:
                user_obj = await db.get_user(target_user_id)
                user_name = (user_obj.get("first_name") or user_obj.get("username") or str(target_user_id)) if user_obj else str(target_user_id)
                token_doc = await db.add_api_token(name=user_name, user_id=target_user_id)
                token_str = token_doc.get("token")
                addon_url = f"{Telegram.BASE_URL}/stremio/{token_str}/manifest.json"
            except Exception as te:
                token_str = None
                addon_url = None

            # Generate invite link for the group
            try:
                invite_link = await client.create_chat_invite_link(
                    chat_id=Telegram.SUBSCRIPTION_GROUP_ID,
                    member_limit=1,
                    expire_date=datetime.utcnow() + timedelta(days=1)
                )
                invite_text = f"\n\n🔗 <b>Grup Daveti:</b> {invite_link.invite_link}"
            except Exception:
                invite_text = ""

            expiry_str = user_data["subscription_expiry"].strftime("%Y-%m-%d")

            # Build confirmation message for user
            success_text = (
                f"🎉 <b>Ödemeniz Onaylandı!</b>\n\n"
                f"Aboneliğiniz <b>{expiry_str} tarihine kadar aktif edildi</b>."
                f"{invite_text}"
            )
            if addon_url:
                success_text += (
                    f"\n\n🎬 <b>Stremio Eklentisi</b>\n"
                    f"<code>{addon_url}</code>\n\n"
                    f"Linki kopyalayıp stremio eklentiler bölümüne ekleyin."
                )

            await client.send_message(target_user_id, success_text)

            # Determine how to format the user/payment info
            duration = user_pre["pending_payment"].get("duration", "?")
            price = user_pre["pending_payment"].get("price", "?")
            
            try:
                target_user = await client.get_users(target_user_id)
                user_mention = target_user.mention
                username_str = f"@{target_user.username}" if target_user.username else "N/A"
            except Exception:
                user_mention = f"User {target_user_id}"
                username_str = "N/A"

            info_text = (
                f"👤 <b>Kullanıcı:</b> {user_mention}\n"
                f"🆔 <b>Kullanıcı ID:</b> <code>{target_user_id}</code>\n"
                f"🔗 <b>Kullanıcı Adı:</b> {username_str}\n\n"
                f"📦 <b>Plan:</b> {duration} gün ({price})TL"
            )

            # Update acting admin's message
            status_caption = f"✅ <b>{admin_name} tarafından onaylandı</b>\n\n{info_text}"
            await callback_query.message.edit_text(status_caption)

            # Update all OTHER admins' copies
            acting_msg_id = callback_query.message.id
            for am in admin_messages:
                if am["message_id"] == acting_msg_id:
                    continue
                try:
                    await client.edit_message_caption(
                        chat_id=am["chat_id"],
                        message_id=am["message_id"],
                        caption=status_caption
                    )
                except Exception:
                    pass
        else:
            await callback_query.answer("Could not approve — no pending payment found.", show_alert=True)

    elif action == "reject":
        success = await db.reject_payment(target_user_id)
        if success:
            await client.send_message(
                target_user_id,
                "❌ <b>Son ödeme gönderiminiz yönetici tarafından reddedildi. Lütfen bilgileri kontrol ederek tekrar deneyin veya yöneticiyle iletişime geçin."
            )

            # Determine how to format the user/payment info
            duration = user_pre["pending_payment"].get("duration", "?")
            price = user_pre["pending_payment"].get("price", "?")
            
            try:
                target_user = await client.get_users(target_user_id)
                user_mention = target_user.mention
                username_str = f"@{target_user.username}" if target_user.username else "N/A"
            except Exception:
                user_mention = f"User {target_user_id}"
                username_str = "N/A"

            info_text = (
                f"👤 <b>Kullanıcı:</b> {user_mention}\n"
                f"🆔 <b>Kullanıcı ID:</b> <code>{target_user_id}</code>\n"
                f"🔗 <b>Kullanıcı Adı:</b> {username_str}\n\n"
                f"📦 <b>Plan:</b> {duration} gün ({price})TL"
            )

            # Update acting admin's message
            status_caption = f"❌ <b>{admin_name} tarafından reddedildi</b>\n\n{info_text}"
            await callback_query.message.edit_caption(status_caption)

            # Update all OTHER admins' copies
            acting_msg_id = callback_query.message.id
            for am in admin_messages:
                if am["message_id"] == acting_msg_id:
                    continue
                try:
                    await client.edit_message_text(
                        chat_id=am["chat_id"],
                        message_id=am["message_id"],
                        caption=status_caption
                    )
                except Exception:
                    pass
        else:
            await callback_query.answer("Could not reject — no pending payment found.", show_alert=True)


@Client.on_message(filters.command("status"))
async def check_status(client: Client, message: Message):
    if not Telegram.SUBSCRIPTION:
        return
        
    user_id = (message.from_user.id if message.from_user else None) or (message.sender_chat.id if message.sender_chat else None) or message.chat.id
        
    user = await db.get_user(user_id)
    if not user or user.get("subscription_status") != "active":
        return await message.reply_text("Aktif bir aboneliğiniz bulunmuyor.")
        
    expiry = user.get("subscription_expiry")
    if not expiry:
        return await message.reply_text("Abonelik bitiş tarihi alınırken bir hata oluştu.")
        
    now = datetime.utcnow()
    if now > expiry:
        return await message.reply_text("Aboneliğinizin süresi dolmuş.")
        
    remaining = expiry - now
    days = remaining.days
    hours = remaining.seconds // 3600
    
    await message.reply_text(
        f"<b>Abonelik Durumu:</b> Aktif ✅\n"
        f"<b>Son Kullanma Tarihi:</b> {expiry.strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"<b>Kalan Süre:</b> {days} gün ve {hours} saat"
    )
