from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import aiosqlite

from database import get_user, create_user, update_user_activity, add_referral
from utils.subscription_check import check_subscriptions
from utils.rating_system import update_user_rating
from keyboards import get_main_menu, get_subscription_keyboard
from messages import WELCOME_MESSAGE, SUBSCRIPTION_REQUIRED_MESSAGE
from config import ADMIN_ID, DATABASE_PATH
from datetime import datetime, timedelta

router = Router()

class StartStates(StatesGroup):
    waiting_for_subscription = State()

async def process_new_referral(referrer_id: int, new_user_id: int, new_user_name: str, bot):
    """Process new referral - update count and check for premium upgrade"""
    try:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            # Update referrer's referral count
            await db.execute("""
                UPDATE users 
                SET referral_count = referral_count + 1 
                WHERE user_id = ?
            """, (referrer_id,))
            
            # Get updated referral count and referrer info
            cursor = await db.execute("""
                SELECT first_name, referral_count, is_premium 
                FROM users WHERE user_id = ?
            """, (referrer_id,))
            referrer_data = await cursor.fetchone()
            
            if not referrer_data:
                return
                
            referrer_name, referral_count, is_premium = referrer_data
            await db.commit()
        
        # Check if referrer reached 10 referrals and isn't already premium
        if referral_count >= 10 and not is_premium:
            # Grant premium for 30 days
            premium_expires_at = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
            
            async with aiosqlite.connect(DATABASE_PATH) as db:
                await db.execute("""
                    UPDATE users 
                    SET is_premium = 1, premium_expires_at = ?
                    WHERE user_id = ?
                """, (premium_expires_at, referrer_id))
                await db.commit()
            
            # Send premium notification
            try:
                await bot.send_message(
                    referrer_id,
                    "🎉🎉🎉 <b>TABRIKLAYMIZ!</b> 🎉🎉🎉\n\n"
                    f"👤 <b>{new_user_name}</b> sizning 10-referalingiz bo'ldi!\n\n"
                    "💎 <b>PREMIUM MUKOFOT:</b>\n"
                    "✅ 30 kunlik premium obuna berildi!\n"
                    "✅ Barcha premium bo'limlarga kirish\n"
                    "✅ Maxsus materiallar va testlar\n"
                    "✅ AI suhbat bilan amaliyot\n\n"
                    f"🗓 Muddat: {premium_expires_at.split()[0]} gacha\n\n"
                    "🚀 Premium imkoniyatlardan foydalaning!",
                    parse_mode="HTML"
                )
            except Exception:
                pass
                
            # Reset referral count for next reward cycle
            async with aiosqlite.connect(DATABASE_PATH) as db:
                await db.execute("""
                    UPDATE users 
                    SET referral_count = 0 
                    WHERE user_id = ?
                """, (referrer_id,))
                await db.commit()
                
        else:
            # Send regular referral notification
            remaining_referrals = max(0, 10 - referral_count)
            try:
                await bot.send_message(
                    referrer_id,
                    f"🎉 <b>Yangi referral!</b>\n\n"
                    f"👤 <b>{new_user_name}</b> sizning taklifingiz bilan qo'shildi!\n\n"
                    f"📊 <b>Referral hisobi:</b>\n"
                    f"✅ Hozirgi: {referral_count}/10\n"
                    f"⏳ Qolgan: {remaining_referrals} ta\n\n"
                    f"💎 {remaining_referrals} ta referral qoldi va 1 oy bepul premium olasiz!",
                    parse_mode="HTML"
                )
            except Exception:
                pass
                
    except Exception as e:
        print(f"Referral processing error: {e}")

@router.message(CommandStart())
async def start_command(message: Message, state: FSMContext):
    if not message.from_user:
        return
    user_id = message.from_user.id
    
    # Check if user exists
    user = await get_user(user_id)
    
    # Handle referral code
    referred_by = None
    if message.text and len(message.text.split()) > 1:
        referral_code = message.text.split()[1]
        # Get referrer by referral code
        import aiosqlite
        from config import DATABASE_PATH
        
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                "SELECT user_id FROM users WHERE referral_code = ?", 
                (referral_code,)
            )
            referrer = await cursor.fetchone()
            if referrer:
                referred_by = referrer[0]
    
    # Create user if doesn't exist
    if not user:
        await create_user(
            user_id=user_id,
            username=message.from_user.username or "",
            first_name=message.from_user.first_name or "",
            last_name=message.from_user.last_name or "",
            referred_by=referred_by
        )
        
        # Add referral record if user was referred
        if referred_by:
            await add_referral(referred_by, user_id)
            await process_new_referral(referred_by, user_id, message.from_user.first_name, message.bot)
    
    # Update user activity
    await update_user_activity(user_id)
    await update_user_rating(user_id, 'session_start')
    
    # Check subscriptions (temporarily disabled for testing)
    # subscription_status = await check_subscriptions(user_id, message.bot)
    
    # if not subscription_status['all_subscribed']:
    #     await message.answer(
    #         SUBSCRIPTION_REQUIRED_MESSAGE.format(
    #             missing_channels=subscription_status['missing_channels']
    #         ),
    #         reply_markup=get_subscription_keyboard()
    #     )
    #     await state.set_state(StartStates.waiting_for_subscription)
    #     return
    
    # User is subscribed, show main menu
    await message.answer(
        WELCOME_MESSAGE.format(
            first_name=message.from_user.first_name
        ),
        reply_markup=get_main_menu(user_id == ADMIN_ID)
    )

@router.callback_query(F.data == "check_subscription")
async def check_subscription_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    subscription_status = await check_subscriptions(user_id, callback.bot)
    
    if not subscription_status['all_subscribed']:
        await callback.answer(
            "❌ Siz hali barcha kanallarga obuna bo'lmagansiz!",
            show_alert=True
        )
        return
    
    # User is now subscribed
    await callback.message.edit_text(
        WELCOME_MESSAGE.format(
            first_name=callback.from_user.first_name
        ),
        reply_markup=get_main_menu(user_id == ADMIN_ID)
    )
    await state.clear()

@router.callback_query(F.data == "main_menu")
async def main_menu_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    # Check subscriptions again
    subscription_status = await check_subscriptions(user_id, callback.bot)
    
    if not subscription_status['all_subscribed']:
        await callback.message.edit_text(
            SUBSCRIPTION_REQUIRED_MESSAGE.format(
                missing_channels=subscription_status['missing_channels']
            ),
            reply_markup=get_subscription_keyboard()
        )
        return
    
    await callback.message.edit_text(
        WELCOME_MESSAGE.format(
            first_name=callback.from_user.first_name
        ),
        reply_markup=get_main_menu(user_id == ADMIN_ID)
    )

@router.message(Command("help"))
async def help_command(message: Message):
    help_text = """
🤖 <b>Bot haqida yordam</b>

<b>Asosiy buyruqlar:</b>
/start - Botni ishga tushirish
/help - Yordam
/profile - Profilingizni ko'rish
/leaderboard - Reytingli foydalanuvchilar ro'yxati

<b>Botdan foydalanish:</b>
1️⃣ Barcha kanallarga obuna bo'ling
2️⃣ Tilni tanlang (Koreys/Yapon)
3️⃣ Bo'limlarni o'rganing
4️⃣ Testlarni bajaring
5️⃣ Premium obuna bo'ling yoki do'stlaringizni taklif qiling

<b>Premium imkoniyatlari:</b>
• Barcha premium kontentlarga kirish
• Maxsus testlar va materiallar
• Kengaytirilgan statistika

<b>Premium olish yo'llari:</b>
💰 Oyiga 50,000 som to'lash
👥 10 ta do'stni taklif qilish (1 oy bepul)

Savollaringiz bo'lsa admin bilan bog'laning: @chang_chi_won
    """
    await message.answer(help_text)

@router.message(Command("profile"))
async def profile_command(message: Message):
    user_id = message.from_user.id
    user = await get_user(user_id)
    
    if not user:
        await message.answer("❌ Foydalanuvchi topilmadi.")
        return
    
    from database import get_user_referrals_count, is_premium_active
    
    referrals_count = await get_user_referrals_count(user_id)
    is_premium = await is_premium_active(user_id)
    
    profile_text = f"""
👤 <b>Sizning profilingiz</b>

🆔 ID: {user_id}
👤 Ism: {user[2]} {user[3] or ''}
📊 Reyting: {user[14]:.1f}
📚 O'rganilgan so'zlar: {user[10]}
🧠 Test natijalari: {user[11]}/{user[12]} (ball/urinish)
📈 Umumiy sessiyalar: {user[9]}

💎 Premium status: {"✅ Faol" if is_premium else "❌ Faol emas"}
👥 Taklif qilinganlar: {referrals_count}/10

🔗 Sizning referral kodingiz: <code>{user[6]}</code>

<i>Bu kodni do'stlaringiz bilan baham ko'ring!</i>
    """
    
    await message.answer(profile_text)

@router.message(Command("leaderboard"))
async def leaderboard_command(message: Message):
    from database import get_leaderboard
    
    try:
        leaders = await get_leaderboard(10)
        
        if not leaders:
            await message.answer("📊 Hozircha reyting jadvalida hech kim yo'q.")
            return
        
        leaderboard_text = "🏆 <b>Top 10 foydalanuvchilar</b>\n\n"
        
        for i, (first_name, rating, words, quiz_score, quiz_attempts) in enumerate(leaders, 1):
            name = first_name or "Noma'lum"
            
            # Medal emojis for top 3
            if i == 1:
                medal = "🥇"
            elif i == 2:
                medal = "🥈"
            elif i == 3:
                medal = "🥉"
            else:
                medal = f"{i}."
            
            leaderboard_text += f"{medal} <b>{name}</b>\n"
            leaderboard_text += f"   📊 Reyting: {rating:.1f}\n"
            leaderboard_text += f"   📚 So'zlar: {words or 0} | 🧠 Test: {quiz_score or 0}\n\n"
        
        await message.answer(leaderboard_text)
        
    except Exception as e:
        await message.answer("❌ Reyting ma'lumotlarini yuklashda xatolik yuz berdi.")



@router.callback_query(F.data == "show_rating")
async def show_rating_callback(callback: CallbackQuery):
    """Show user's detailed rating and leaderboard"""
    user_id = callback.from_user.id
    
    try:
        from database import get_user, get_leaderboard
        
        # Get user data from database
        user = await get_user(user_id)
        if not user:
            await callback.answer("❌ Foydalanuvchi ma'lumotlari topilmadi!", show_alert=True)
            return
        
        # Extract user data
        rating_score = user[14] if len(user) > 14 else 0.0  # rating_score
        words_learned = user[10] if len(user) > 10 else 0   # words_learned
        quiz_score = user[11] if len(user) > 11 else 0      # quiz_score_total
        quiz_attempts = user[12] if len(user) > 12 else 0   # quiz_attempts
        total_sessions = user[9] if len(user) > 9 else 0    # total_sessions
        
        # Calculate level and ranking
        level = min(100, max(1, int(rating_score / 50) + 1))
        
        # Get ranking by counting users with higher rating
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute("""
                SELECT COUNT(*) + 1 as ranking
                FROM users 
                WHERE rating_score > ? AND rating_score > 0
            """, (rating_score,))
            ranking = (await cursor.fetchone())[0]
        
        # Get top 8 users with highest ratings and best performance  
        leaderboard = await get_leaderboard(8)
        
        # Color code based on rating
        if rating_score >= 200:
            level_emoji = "🥇"
            level_color = "OLTIN"
        elif rating_score >= 100:
            level_emoji = "🥈"
            level_color = "KUMUSH"
        elif rating_score >= 50:
            level_emoji = "🥉"
            level_color = "BRONZA"
        else:
            level_emoji = "📊"
            level_color = "BOSHLANG'ICH"
        
        rating_text = f"""📊 <b>SIZNING REYTINGINGIZ</b>
        
{level_emoji} <b>Daraja:</b> {level} ({level_color})
📈 <b>Reyting:</b> {rating_score:.1f} ball
🏆 <b>O'rin:</b> {ranking}-chi
📚 <b>O'rganilgan so'zlar:</b> {words_learned}
🧠 <b>Test natijalari:</b> {quiz_score}/{quiz_attempts}
📱 <b>Umumiy sessiyalar:</b> {total_sessions}

🏆 <b>TOP 8 ENG YAXSHI FOYDALANUVCHILAR</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
        
        # Add leaderboard - show top 8 users
        if leaderboard and len(leaderboard) > 0:
            for i, leader in enumerate(leaderboard[:8], 1):
                user_id_leader, first_name, username, rating, words, quiz_score_leader, quiz_attempts_leader = leader
                name = first_name or "Noma'lum"
                
                if i == 1:
                    medal = "🥇"
                elif i == 2:
                    medal = "🥈" 
                elif i == 3:
                    medal = "🥉"
                else:
                    medal = f"{i}."
                
                # Highlight current user
                if user_id_leader == callback.from_user.id:
                    rating_text += f"\n{medal} <b>👤 {name} (SIZ)</b> - {rating:.1f} ball"
                else:
                    rating_text += f"\n{medal} <b>{name}</b> - {rating:.1f} ball"
            
            # Show total users count
            rating_text += f"\n\n👥 <b>Jami ishtirokchilar:</b> {len(leaderboard)} ta"
        else:
            rating_text += f"\n\n🎯 <b>Birinchi bo'ling!</b>"
            rating_text += f"\n• Testlarni ishlang va ball to'plang"
            rating_text += f"\n• So'zlarni o'rganing va reyting oshiring"
            rating_text += f"\n• Boshqa o'quvchilar qo'shilganida siz birinchi bo'lasiz!"
        
        next_level_points = (level * 50) - rating_score
        if next_level_points > 0:
            rating_text += f"\n\n💡 <b>Keyingi daraja uchun:</b> {next_level_points:.1f} ball kerak"
        else:
            rating_text += f"\n\n🎉 <b>Siz eng yuqori darajadasiz!</b>"
        
        # Add motivational message
        if rating_score == 0:
            rating_text += f"\n\n🚀 <b>Boshlang:</b> Birinchi testni ishlang!"
        elif rating_score < 10:
            rating_text += f"\n\n📚 <b>Davom eting:</b> Ko'proq test ishlang!"
        elif rating_score < 50:
            rating_text += f"\n\n⭐ <b>Ajoyib:</b> Siz yaxshi yo'ldasiz!"
        else:
            rating_text += f"\n\n🏆 <b>Zo'r:</b> Siz professional darajada!"
        
        try:
            await callback.message.edit_text(rating_text, reply_markup=get_main_menu(user_id == ADMIN_ID))
        except Exception as edit_error:
            if "message is not modified" in str(edit_error).lower():
                await callback.answer("📊 Ma'lumotlar allaqachon yangi", show_alert=False)
            else:
                raise edit_error
        
    except Exception as e:
        print(f"Rating callback error: {e}")
        # Fallback to simple rating display
        try:
            user = await get_user(user_id)
            if user:
                rating_score = user[14] if len(user) > 14 else 0.0
                words_learned = user[10] if len(user) > 10 else 0
                simple_text = f"""📊 <b>SIZNING REYTINGINGIZ</b>

📈 <b>Reyting:</b> {rating_score:.1f} ball
📚 <b>O'rganilgan so'zlar:</b> {words_learned}

🔄 <b>Batafsil ma'lumot yuklanmoqda...</b>
Iltimos, qaytadan urinib ko'ring."""
                await callback.message.edit_text(simple_text, reply_markup=get_main_menu(user_id == ADMIN_ID))
            else:
                await callback.answer("❌ Foydalanuvchi ma'lumotlari topilmadi!", show_alert=True)
        except:
            await callback.answer("❌ Reyting ma'lumotlarini yuklashda xatolik!", show_alert=True)

# Admin panel handler is in handlers/admin.py

@router.callback_query(F.data == "rating")
async def show_rating(callback: CallbackQuery):
    """Reyting va statistika bo'limi - XATOLIKSIZ"""
    user_id = callback.from_user.id
    
    try:
        from database import get_user, get_leaderboard
        
        # Direct user data olish
        user = await get_user(user_id)
        if not user:
            await callback.message.edit_text(
                "❌ Foydalanuvchi ma'lumotlari topilmadi.",
                reply_markup=get_main_menu(user_id == ADMIN_ID)
            )
            await callback.answer()
            return
        
        # Safe data extraction
        first_name = str(user[2]) if len(user) > 2 and user[2] else 'Anonim'
        rating_score = float(user[14]) if len(user) > 14 and user[14] is not None else 0.0
        words_learned = int(user[11]) if len(user) > 11 and user[11] is not None else 0
        quiz_score_total = int(user[12]) if len(user) > 12 and user[12] is not None else 0
        quiz_attempts = int(user[13]) if len(user) > 13 and user[13] is not None else 0
        total_sessions = int(user[10]) if len(user) > 10 and user[10] is not None else 0
        
        # Calculate level
        level = min(100, max(1, int(rating_score / 50) + 1))
        
        # Rating text yaratish
        rating_text = f"""📊 <b>SIZNING REYTINGINGIZ</b>

👤 <b>Ism:</b> {first_name}
🏆 <b>Reyting ball:</b> {rating_score:.1f}
📈 <b>Daraja:</b> {level} 
📚 <b>O'rganilgan so'zlar:</b> {words_learned}
🎯 <b>Quiz balli:</b> {quiz_score_total}
📝 <b>Quiz urinishlari:</b> {quiz_attempts}
💻 <b>Jami sessiyalar:</b> {total_sessions}"""

        # Leaderboard qo'shish - xatoliksiz
        try:
            leaderboard = await get_leaderboard(5)
            if leaderboard and len(leaderboard) > 0:
                rating_text += f"\n\n⭐ <b>TOP 5 LIDERLAR:</b>\n"
                for i, leader in enumerate(leaderboard, 1):
                    if leader and len(leader) >= 2:
                        name = str(leader[0]) if leader[0] else 'Anonim'
                        score = float(leader[1]) if leader[1] is not None else 0.0
                        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                        rating_text += f"{medal} {name}: {score:.1f} ball\n"
            else:
                rating_text += f"\n\n📊 <b>Hozircha boshqa liderlar yo'q.</b>"
        except Exception as le:
            print(f"Leaderboard error: {le}")
            rating_text += f"\n\n📊 <b>Liderlar ro'yxati yuklanmoqda...</b>"
        
        # Motivational message
        if rating_score == 0:
            rating_text += f"\n\n🚀 <b>Boshlang:</b> Birinchi testni ishlang!"
        elif rating_score < 10:
            rating_text += f"\n\n📚 <b>Davom eting:</b> Ko'proq test ishlang!"
        elif rating_score < 50:
            rating_text += f"\n\n⭐ <b>Ajoyib:</b> Siz yaxshi yo'ldasiz!"
        else:
            rating_text += f"\n\n🏆 <b>Zo'r:</b> Siz professional darajada!"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Yangilash", callback_data="rating")],
            [InlineKeyboardButton(text="🏠 Bosh menu", callback_data="main_menu")]
        ])
        
        await callback.message.edit_text(rating_text, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer("📊 Reyting yangilandi!")
            
    except Exception as e:
        print(f"Rating handler critical error: {e}")
        # Ultimate fallback
        simple_text = f"""📊 <b>REYTING</b>

❌ Ma'lumot yuklashda xatolik.
Iltimos qayta urinib ko'ring.

🔄 Yangilash tugmasini bosing."""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Qayta urinish", callback_data="rating")],
            [InlineKeyboardButton(text="🏠 Bosh menu", callback_data="main_menu")]
        ])
        
        await callback.message.edit_text(simple_text, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer("❌ Xatolik!")

@router.callback_query(F.data == "conversation")
async def show_conversation_menu(callback: CallbackQuery):
    """Premium AI suhbat menu"""
    user_id = callback.from_user.id
    user = await get_user(user_id)
    
    # Premium foydalanuvchi tekshiruvi
    from database import is_premium_active
    is_premium = await is_premium_active(user_id) if user else False
    
    if not is_premium:
        # Premium reklama xabari
        
        premium_ad_text = """🤖 <b>AI bilan suhbat - Premium xizmat</b>

🌟 <b>PREMIUM AI BILAN SUHBAT AFZALLIKLARI:</b>

🧠 <b>Haqiqiy AI tajriba:</b>
• Sizni tushunuvchi va javob beruvchi AI
• Kores va yapon tillarida professional suhbat
• 12,000+ so'z va ibora lug'ati
• Cultural awareness va context understanding

💎 <b>Exclusive Premium foydalari:</b>
• Cheksiz AI suhbat sessiyalari
• Har xabar uchun +1.5 reyting ball
• Personal AI language tutor
• 24/7 mavjudlik va tez javob

🚀 <b>Til o'rganishda super tezlik:</b>
• Interactive conversation practice
• Real-time grammar correction
• Vocabulary expansion
• Pronunciation guidance

📈 <b>Progress tracking:</b>
• Sizning til darajangizni kuzatadi
• Individual learning path
• Achievement system
• Weekly progress reports

💰 <b>Premium obuna:</b>
• Oyiga 50,000 som
• Yoki 10 ta referral = 1 oy bepul
• Premium content access
• AI conversation unlimited

🎯 <b>Natija kafolati:</b>
• 30 kun ichida sezilarli o'sish
• Professional conversation skills
• Native speaker confidence level
• Sertifikat olish imkoniyati"""

        premium_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="💎 Premium sotib olish", callback_data="premium")
            ],
            [
                InlineKeyboardButton(text="👥 10 Referral to'plash", callback_data="referral_program")
            ],
            [
                InlineKeyboardButton(text="🔙 Bosh menu", callback_data="main_menu")
            ]
        ])
        
        await callback.message.edit_text(
            premium_ad_text,
            reply_markup=premium_keyboard
        )
    else:
        # Premium foydalanuvchi uchun AI suhbat
        from keyboards import get_conversation_menu
        await callback.message.edit_text(
            "🤖 <b>Premium AI bilan suhbat</b>\n\n✨ Siz Premium a'zosiz! Tilni tanlang:",
            reply_markup=get_conversation_menu()
        )


@router.callback_query(F.data == "premium")  
async def show_premium_menu(callback: CallbackQuery):
    """Premium xizmat menyusi"""
    user_id = callback.from_user.id
    
    try:
        from database import is_premium_active, get_user, get_user_stats
        user = await get_user(user_id)
        is_premium = await is_premium_active(user_id) if user else False
        
        if is_premium:
            premium_text = """✅ <b>Siz Premium foydalanuvchisiz!</b>

🎉 <b>Premium imkoniyatlar:</b>
🤖 AI bilan suhbat: Korean va Japanese AI
📚 Barcha premium bo_limlar
🏆 JLPT testlari
📊 Advanced statistika"""

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🤖 AI bilan suhbat", callback_data="conversation")],
                [InlineKeyboardButton(text="📚 Bo'limlar", callback_data="sections")],
                [InlineKeyboardButton(text="🔙 Bosh menu", callback_data="main_menu")]
            ])
        else:
            user_stats = await get_user_stats(user_id)
            referral_count = user_stats.get('referral_count', 0) if user_stats else 0
            remaining_referrals = max(0, 10 - referral_count)
            
            premium_text = f"""💎 <b>PREMIUM OBUNA - Til o'rganishda yutuq!</b>

🎯 <b>NEGA PREMIUM TANLASHINGIZ KERAK?</b>

🧠 <b>AI Ustoz - Shaxsiy o'qituvchi:</b>
• 12,000+ so'z lug'ati bilan Korean AI
• 12,000+ so'z lug'ati bilan Japanese AI  
• Uzun gaplarga professional javob
• Har xabar uchun +1.5 reyting ball

📚 <b>Exclusive Premium Content:</b>
• Barcha premium bo'limlar ochiq
• JLPT N5-N1 professional testlar
• Advanced grammar patterns
• Cultural context va pronunciation

🚀 <b>Natija kafolati:</b>
• 30 kun ichida sezilarli o'sish
• Professional conversation skills
• Native speaker confidence level

💰 <b>NARX va TO'LOV:</b>
• Faqat 50,000 som/oy (kuniga 1,600 som!)
• YOKI 10 referral = 1 oy BEPUL
• Sizda: {referral_count}/10 referral
• Kerak: yana {remaining_referrals} ta

⏰ <b>BUGUN BOSHLAMASLIK UCHUN SABAB YO'Q!</b>
Har kun kechikish - o'tkazib yuborilgan imkoniyat!"""

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💎 HOZIROQ SOTIB OLISH", callback_data="premium_purchase")],
                [InlineKeyboardButton(text="👥 Referral dasturi", callback_data="referral_program")],
                [InlineKeyboardButton(text="🆓 Bepul premium (10 referral)", callback_data="referral_info")],
                [InlineKeyboardButton(text="🔙 Bosh menu", callback_data="main_menu")]
            ])
        
        await callback.message.edit_text(premium_text, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer()
        
    except Exception as e:
        print(f"Premium menu error: {e}")
        await callback.answer("❌ Xatolik!")

@router.callback_query(F.data == "premium_purchase")
async def handle_premium_purchase(callback: CallbackQuery):
    """Premium sotib olish handler"""
    try:
        purchase_text = """💎 <b>PREMIUM SOTIB OLISH</b>

🔥 <b>MAXSUS TAKLIF - Faqat bugun!</b>

💳 <b>TO'LOV USULI:</b>

🏦 <b>KAPITAL BANK VISA KARTA:</b>
• Karta raqami: 4278 3100 2775 4068
• Egasi: Xoshimjon Mamadiyev
• Summa: 50,000 som
• Izoh: "Premium - @{username}"

📞 <b>TO'LOV QILGANINGIZDAN KEYIN:</b>
1. To'lov screenshot/chek surat oling
2. @Chang_chi_won ga yuboring  
3. 5 daqiqa ichida Premium faollashtiriladi!

🌏 <b>LOKATSIYA:</b> Janubiy Koreya - Seul, Inchon

⚡ <b>DIQQAT:</b> Premium faollashtirilgandan keyin darhol barcha AI va content ochiladi!

🎁 <b>BONUS:</b> Birinchi 100 ta sotib oluvchi uchun +500 reyting ball BEPUL!"""

        purchase_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Admin bilan bog'lanish", url="https://t.me/Chang_chi_won")],
            [InlineKeyboardButton(text="📸 To'lov tasdiqlash", url="https://t.me/Chang_chi_won")],
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="premium")]
        ])
        
        await callback.message.edit_text(
            purchase_text, 
            reply_markup=purchase_keyboard,
            parse_mode="HTML"
        )
        await callback.answer()
        
    except Exception as e:
        print(f"Premium purchase error: {e}")
        await callback.answer("❌ Xatolik!")

@router.callback_query(F.data == "referral_program")  
async def handle_referral_program(callback: CallbackQuery):
    """Referral dasturi handler"""
    try:
        user_id = callback.from_user.id
        username = callback.from_user.username or "user"
        
        from database import get_user_stats
        user_stats = await get_user_stats(user_id)
        referral_count = user_stats.get('referral_count', 0)
        remaining_referrals = max(0, 10 - referral_count)
        
        referral_text = f"""👥 <b>REFERRAL DASTURI - Bepul Premium!</b>

🎯 <b>SIZNING HOLATINGIZ:</b>
• Hozirgi referrallar: {referral_count}/10
• Kerak: yana {remaining_referrals} ta
• Progress: {'█' * referral_count}{'░' * remaining_referrals}

🚀 <b>QANDAY ISHLAYDI:</b>

1️⃣ <b>Referral havolangiz:</b>
`https://t.me/KoreYap_ProGradBot?start=ref_{user_id}`

2️⃣ <b>Bu havolani ulashing:</b>
• Do'stlaringizga yuboring
• Social media da e'lon qiling  
• Telegram guruhlariga tashlang
• Familia a'zolariga ko'rsating

3️⃣ <b>Natija:</b>
• Har yangi a'zo = +1 referral
• 10 referral = 30 kun BEPUL Premium!
• Premium olgandan keyin hisoblagich qayta boshlanadi

🎁 <b>QO'SHIMCHA MUKOFOTLAR:</b>
• 5 referral = +100 reyting ball
• 10 referral = 30 kun Premium + 500 ball
• 20 referral = 60 kun Premium + 1000 ball

💡 <b>MASLAHAT:</b>
"Korean va yapon tilini bepul o'rganing! Professional AI ustoz bilan!" deb yozing va havolani qo'shing.

⚡ <b>DIQQAT:</b> Faqat real foydalanuvchilar hisoblanadi (spam yo'q!)"""

        referral_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Havolani nusxalash", callback_data="copy_referral_link")],
            [InlineKeyboardButton(text="📊 Referral statistika", callback_data="referral_stats")],
            [InlineKeyboardButton(text="🎁 Mukofotlarim", callback_data="my_rewards")],
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="premium")]
        ])
        
        await callback.message.edit_text(
            referral_text,
            reply_markup=referral_keyboard, 
            parse_mode="HTML"
        )
        await callback.answer()
        
    except Exception as e:
        print(f"Referral program error: {e}")
        await callback.answer("❌ Xatolik!")

@router.callback_query(F.data == "referral_info")
async def handle_referral_info(callback: CallbackQuery):
    """Referral ma'lumot handler"""
    try:
        info_text = """🆓 <b>BEPUL PREMIUM OLISH YO'LI</b>

🎯 <b>10 REFERRAL = 1 OY BEPUL PREMIUM!</b>

💰 <b>HISOB-KITOB:</b>
• Premium narxi: 50,000 som/oy
• 10 referral = 50,000 som tejash
• Har referral = 5,000 som qiymat!

⏰ <b>QANCHA VAQT KETADI:</b>
• Faol bo'lsangiz: 1-2 kun
• Oddiy tarzda: 1 hafta
• Kechiktirgan holda: 1 oy

🚀 <b>ENG SAMARALI USULLAR:</b>

📱 <b>Social Media:</b>
• Instagram Stories da e'lon
• Facebook post qiling
• TikTok da video yarating
• YouTube Short tayyorlang

👥 <b>Do'stlar va oila:</b>  
• WhatsApp guruhlarda ulashing
• Telegram kanallarda reklama
• Sinfdoshlaringizga ayting
• Ish joyidagi hamkasblar

📚 <b>Ta'lim jamoalari:</b>
• Tillar o'rganish guruhlarida
• Universitet telegram kanallarida  
• Online ta'lim platformalarida
• Language exchange chatlarida

🎁 <b>NATIJA:</b>
30 kun davomida barcha Premium imkoniyatlar BEPUL!"""

        info_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Referral boshlash", callback_data="referral_program")],
            [InlineKeyboardButton(text="💎 Premium sotib olish", callback_data="premium_purchase")],
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="premium")]
        ])
        
        await callback.message.edit_text(
            info_text,
            reply_markup=info_keyboard,
            parse_mode="HTML"
        )
        await callback.answer()
        
    except Exception as e:
        print(f"Referral info error: {e}")
        await callback.answer("❌ Xatolik!")

@router.callback_query(F.data == "copy_referral_link")
async def handle_copy_referral_link(callback: CallbackQuery):
    """Referral havolani nusxalash handler"""
    try:
        user_id = callback.from_user.id
        referral_link = f"https://t.me/KoreYap_ProGradBot?start=ref_{user_id}"
        
        copy_text = f"""📋 <b>REFERRAL HAVOLANGIZ</b>

🔗 <b>Havola:</b>
`{referral_link}`

📱 <b>QANDAY ULASHISH:</b>

1️⃣ <b>Yuqoridagi havolani nusxalang</b>
2️⃣ <b>Do'stlaringizga yuboring:</b>
   • WhatsApp, Telegram, Instagram
   • Facebook, TikTok, YouTube
   • Sinf guruhlariga, ish joyida
   
3️⃣ <b>Matn bilan birga yuboring:</b>
"🇰🇷 Korean va 🇯🇵 Yapon tillarini AI bilan bepul o'rganing! Professional ustoz kabi o'rgatadi!"

⚡ <b>HAR YANGI A'ZO = +1 REFERRAL</b>
🎁 <b>10 REFERRAL = 30 KUN BEPUL PREMIUM!</b>"""

        copy_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Yangi havola", callback_data="copy_referral_link")],
            [InlineKeyboardButton(text="📊 Statistika", callback_data="referral_stats")],
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="referral_program")]
        ])
        
        await callback.message.edit_text(
            copy_text,
            reply_markup=copy_keyboard,
            parse_mode="HTML"
        )
        await callback.answer("📋 Havola tayyor! Nusxalang va ulashing!")
        
    except Exception as e:
        print(f"Copy referral link error: {e}")
        await callback.answer("❌ Xatolik!")

@router.callback_query(F.data == "referral_stats")
async def handle_referral_stats(callback: CallbackQuery):
    """Referral statistika handler"""
    try:
        user_id = callback.from_user.id
        
        from database import get_user_stats
        user_stats = await get_user_stats(user_id)
        referral_count = user_stats.get('referral_count', 0)
        remaining_referrals = max(0, 10 - referral_count)
        
        # Progress bar yaratish
        filled_blocks = referral_count
        empty_blocks = 10 - referral_count
        progress_bar = "█" * filled_blocks + "░" * empty_blocks
        
        stats_text = f"""📊 <b>REFERRAL STATISTIKANGIZ</b>

👥 <b>HOZIRGI HOLAT:</b>
• Referrallaringiz: {referral_count}/10
• Kerak: yana {remaining_referrals} ta
• Progress: {progress_bar}

🎯 <b>MAQSAD:</b>
{10 - referral_count} ta referral qoldi - 30 kun BEPUL Premium uchun!

💰 <b>QIYMAT HISOBLASH:</b>
• Hozirgi referrallar: {referral_count} × 5,000 = {referral_count * 5000:,} som
• To'liq mukofot: 10 × 5,000 = 50,000 som
• Qolgan qiymat: {remaining_referrals * 5000:,} som

📈 <b>KEYINGI MUKOFOTLAR:</b>"""

        if referral_count < 5:
            stats_text += f"\n• {5 - referral_count} ta referral → +100 reyting ball"
        if referral_count < 10:
            stats_text += f"\n• {10 - referral_count} ta referral → 30 kun Premium + 500 ball"
        if referral_count < 20:
            stats_text += f"\n• {20 - referral_count} ta referral → 60 kun Premium + 1000 ball"

        stats_text += f"""

🚀 <b>MASLAHAT:</b>
{"Zo'r ish! Davom eting!" if referral_count > 0 else "Birinchi referralingizni oling!"}"""

        stats_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Havola olish", callback_data="copy_referral_link")],
            [InlineKeyboardButton(text="🎁 Mukofotlarim", callback_data="my_rewards")],
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="referral_program")]
        ])
        
        await callback.message.edit_text(
            stats_text,
            reply_markup=stats_keyboard,
            parse_mode="HTML"
        )
        await callback.answer()
        
    except Exception as e:
        print(f"Referral stats error: {e}")
        await callback.answer("❌ Xatolik!")

@router.callback_query(F.data == "my_rewards")
async def handle_my_rewards(callback: CallbackQuery):
    """Mening mukofotlarim handler"""
    try:
        user_id = callback.from_user.id
        
        from database import get_user_stats, is_premium_active
        user_stats = await get_user_stats(user_id)
        referral_count = user_stats.get('referral_count', 0)
        is_premium = await is_premium_active(user_id)
        
        rewards_text = f"""🎁 <b>MENING MUKOFOTLARIM</b>

👥 <b>REFERRALLAR:</b> {referral_count}/10

🏆 <b>OLINGAN MUKOFOTLAR:</b>"""

        # Mukofotlarni tekshirish
        earned_rewards = []
        pending_rewards = []
        
        if referral_count >= 5:
            earned_rewards.append("✅ 5 referral: +100 reyting ball")
        else:
            pending_rewards.append(f"⏳ 5 referral: +100 reyting ball ({5 - referral_count} ta kerak)")
            
        if referral_count >= 10:
            earned_rewards.append("✅ 10 referral: 30 kun Premium + 500 ball")
        else:
            pending_rewards.append(f"⏳ 10 referral: 30 kun Premium + 500 ball ({10 - referral_count} ta kerak)")
            
        if referral_count >= 20:
            earned_rewards.append("✅ 20 referral: 60 kun Premium + 1000 ball")
        else:
            pending_rewards.append(f"⏳ 20 referral: 60 kun Premium + 1000 ball ({20 - referral_count} ta kerak)")

        if earned_rewards:
            rewards_text += "\n" + "\n".join(earned_rewards)
        else:
            rewards_text += "\nHali mukofot yo'q - birinchi referralingizni oling!"

        rewards_text += f"""

🔮 <b>KEYINGI MUKOFOTLAR:</b>
{chr(10).join(pending_rewards) if pending_rewards else "Barcha mukofotlarni oldingiz! 🎉"}

💎 <b>PREMIUM STATUS:</b> {"✅ Faol" if is_premium else "❌ Faol emas"}

💡 <b>ESLATMA:</b>
Mukofotlar avtomatik beriladi - referral to'planganda darhol faollashadi!"""

        rewards_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Ko'proq referral", callback_data="copy_referral_link")],
            [InlineKeyboardButton(text="📊 Statistika", callback_data="referral_stats")],
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="referral_program")]
        ])
        
        await callback.message.edit_text(
            rewards_text,
            reply_markup=rewards_keyboard,
            parse_mode="HTML"
        )
        await callback.answer()
        
    except Exception as e:
        print(f"My rewards error: {e}")
        await callback.answer("❌ Xatolik!")

