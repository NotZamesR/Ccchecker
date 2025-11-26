import re
import asyncio
import logging
import aiohttp
import signal
import sys
import random
import os
from datetime import datetime, timezone
from pyrogram import Client, idle
from pyrogram.enums import ParseMode, ChatType
from pyrogram.errors import FloodWait, UserAlreadyParticipant, InviteHashExpired, InviteHashInvalid
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiohttp import web
import pytz 

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


API_ID = "29021447" #replace 
API_HASH = "303c8886fed6409c9d0cda4cf5a41905"
PHONE_NUMBER = "+84349253553"
TARGET_GROUP = -1002711360849

PHOTO_URLS = [
    "https://t.me/livedroppy/32", "https://t.me/rar_xdd/4", "https://t.me/rar_xdd/5",
    "https://t.me/rar_xdd/6", "https://t.me/rar_xdd/7", "https://t.me/rar_xdd/9",
] #photo 

MAX_CONCURRENT_GROUPS = 3
MESSAGE_BATCH_SIZE = 20
POLL_INTERVAL = 12
MIN_SEND_DELAY = 15
MAX_SEND_DELAY = 20
REQUEST_DELAY = 1.0


user = Client("cc_monitor_user", api_id=API_ID, api_hash=API_HASH, phone_number=PHONE_NUMBER)

#@diwazz
is_running = True
last_processed_message_ids = {}
hourly_scraped_ccs = []
hourly_report_lock = asyncio.Lock()

#@diwazz
def is_approved_message(text):
    if not text: return False
    text_lower = text.lower()
    approved_patterns = [
        r'approved', r'charged', r'payment\s+successful', r'thank\s+you', r'order_placed'
    ]
    return any(re.search(pattern, text_lower, re.IGNORECASE) for pattern in approved_patterns)

def extract_credit_cards(text):
    if not text: return []
    patterns = [r'(\d{13,19})[\|\s\/\-:]+(\d{1,2})[\|\s\/\-:]+(\d{2,4})[\|\s\/\-:]+(\d{3,4})']
    credit_cards = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            card_number, month, year, cvv = match.groups()
            card_number = re.sub(r'[\s\-]', '', card_number)
            if 13 <= len(card_number) <= 19 and 1 <= int(month) <= 12 and len(cvv) >= 3:
                year_digits = year[-2:]
                credit_cards.append(f"{card_number}|{month.zfill(2)}|{year_digits}|{cvv}")
    return list(dict.fromkeys(credit_cards))

async def get_bin_info(bin_number):
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(f"https://bins.antipublic.cc/bins/{bin_number}") as response:
                if response.status == 200: return await response.json()
    except Exception: return None

#@diwazz
def format_card_message(cc_data, bin_info):
    bin_info = bin_info or {}
    card_number, month, year, cvv = cc_data.split('|')
    bin_number = card_number[:6]
    
    scheme = bin_info.get('brand', 'N/A').upper()
    card_type = bin_info.get('type', 'N/A').upper()
    issuer = bin_info.get('bank', 'N/A')
    country = bin_info.get('country_name', 'N/A')
    
    current_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    
    cc_display = f"{card_number}|{month}|{year}|{cvv}"

    return (f"**Xebec Scrapper** \n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"**[💳] 𝗖𝗖 ⇾** `{cc_display}`\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"**[💰] 𝙎𝙏𝘼𝙏𝙐𝙎 ⇾** `𝘈𝘱𝘱𝘳𝘰𝘷𝘦𝘥 💎`\n"
            f"**[💬] 𝙈𝙀𝙎𝙎𝘼𝙂𝙀 ⇾** `𝘚𝘤𝘳𝘢𝘱𝘱𝘦𝘥 𝘚𝘶𝘤𝘤𝘦𝘴𝘴𝘧𝘶𝘭𝘭𝘺`\n"
            f"**[ GATEWAY ] ⇾** `𝘚𝘤𝘳𝘢𝘱𝘱𝘦𝘳 🍑`\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"**[🌐] 𝗕𝗶𝗻 ⇾** `{bin_number}`\n"
            f"**[🗺️] 𝗖𝗼𝘂𝗻𝘁𝗿𝘆 ⇾** {country}\n"
            f"**[🏦] 𝗜𝘀𝘀𝘂𝗲𝗿 ⇾** {issuer}\n"
            f"**[✨] 𝗧𝘆𝗽𝗲 ⇾** {card_type} - {scheme}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"**[⏰] 𝗧𝗶𝗺𝗲 ⇾** {current_time}\n"
            f"**[👤] 𝗦𝗰𝗿𝗮𝗽𝗽𝗲𝗱 𝗕𝘆 ⇾** @diwazz")

# @diwazz
async def send_to_target_group(formatted_message, cc_data):
    global hourly_scraped_ccs
    try:
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("𝗟𝗶𝘃𝗲 𝗖𝗖", url="https://t.me/livedropp")],
            [InlineKeyboardButton("𝗢𝘄𝗻𝗲𝗿", url="https://t.me/diwazz")]
        ])
        
        random_photo = random.choice(PHOTO_URLS)
        
        await user.send_photo(
            chat_id=TARGET_GROUP, photo=random_photo, caption=formatted_message,
            parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
        )
        
        card_number = cc_data.split('|')[0]
        logger.info(f"✅ Sent CC {card_number[:6]}...{card_number[-4:]} to target group.")
        
        async with hourly_report_lock:
            hourly_scraped_ccs.append(cc_data)
            
        delay = random.randint(MIN_SEND_DELAY, MAX_SEND_DELAY)
        await asyncio.sleep(delay)
        
    except FloodWait as e:
        logger.warning(f"⏳ Flood wait of {e.value}s on sending. Waiting...")
        await asyncio.sleep(e.value)
    except Exception as e:
        logger.error(f"❌ Failed to send message to target group: {e}")

async def process_message_for_approved_ccs(message):
    text = message.text or message.caption
    if not text or not is_approved_message(text): return

    credit_cards = extract_credit_cards(text)
    if not credit_cards: return

    logger.info(f"🎯 Found {len(credit_cards)} approved CC(s) in '{message.chat.title[:25]}'.")
    for cc_data in credit_cards:
        bin_info = await get_bin_info(cc_data.split('|')[0][:6])
        formatted_message = format_card_message(cc_data, bin_info)
        await send_to_target_group(formatted_message, cc_data)

async def poll_single_group(group_info):
    try:
        messages = [msg async for msg in user.get_chat_history(group_info['id'], limit=MESSAGE_BATCH_SIZE)]
        if not messages: return

        last_id = last_processed_message_ids.get(group_info['id'], 0)
        new_messages = sorted([msg for msg in messages if msg.id > last_id], key=lambda m: m.id)

        if new_messages:
            for message in new_messages: await process_message_for_approved_ccs(message)
            last_processed_message_ids[group_info['id']] = new_messages[-1].id
    except Exception: pass

async def poll_all_groups():
    logger.info("🔄 Starting multi-group polling...")
    source_groups = await get_all_groups_and_channels()
    if not source_groups:
        logger.error("❌ No source groups found to monitor!")
        return

    logger.info(f"📡 Monitoring {len(source_groups)} groups/channels.")
    for group in source_groups:
        try:
            messages = [msg async for msg in user.get_chat_history(group['id'], limit=1)]
            last_processed_message_ids[group['id']] = messages[0].id if messages else 0
        except Exception: last_processed_message_ids[group['id']] = 0
    logger.info("✅ All groups initialized.")

    while is_running:
        random.shuffle(source_groups)
        for i in range(0, len(source_groups), MAX_CONCURRENT_GROUPS):
            if not is_running: break
            batch = source_groups[i:i + MAX_CONCURRENT_GROUPS]
            await asyncio.gather(*(poll_single_group(g) for g in batch))
            await asyncio.sleep(REQUEST_DELAY)
        logger.info(f"✅ Poll cycle complete. Waiting {POLL_INTERVAL}s...")
        await asyncio.sleep(POLL_INTERVAL)

#@diwazz
async def send_hourly_report():
    global hourly_scraped_ccs
    async with hourly_report_lock:
        if not hourly_scraped_ccs:
            logger.info("No CCs scraped in the last hour. Skipping report.")
            return

        cc_count = len(hourly_scraped_ccs)
        report_caption = (f"```\n"
                          f"╔═════════════════════════════╗\n"
                          f"  -ˋˏ ✨ 𝗫𝗘𝗕𝗘𝗖 𝗛𝗢𝗨𝗥𝗟𝗬 𝗣𝗘𝗥𝗙𝗢𝗥𝗠𝗔𝗡𝗖𝗘 ✨ ˎˊ-\n"
                          f"╚═════════════════════════════╝\n"
                          f"┠─» 📈 𝗖𝗖 𝗦𝗖𝗥𝗔𝗣𝗘𝗗 ⇾ {cc_count}\n"
                          f"┠─» ⏳ 𝗡𝗘𝗫𝗧 𝗥𝗘𝗣𝗢𝗥𝗧 ⇾ In 1 hour\n"
                          f"╚═» 👑 𝗗𝗘𝗩𝗘𝗟𝗢𝗣𝗘𝗥 ⇾ @diwazz\n"
                          f"```")
        
        file_path = "xebec.txt"
        with open(file_path, "w") as f: f.write("\n".join(hourly_scraped_ccs))
        
        try:
            report_message = await user.send_document(chat_id=TARGET_GROUP, document=file_path, caption=report_caption, parse_mode=ParseMode.MARKDOWN)
            await report_message.pin(disable_notification=True)
            logger.info(f"✅ Hourly report sent and pinned with {cc_count} CCs.")
        except Exception as e:
            logger.error(f"❌ Failed to send or pin hourly report: {e}")
        finally:
            os.remove(file_path)
            hourly_scraped_ccs = []

async def send_promo_message():
    promo_text = (f"```\n"
                  f"╔═════════════════════════════╗\n"
                  f"    -ˋˏ 💎 𝗝𝗢𝗜𝗡 𝗧𝗛𝗘 𝗘𝗟𝗜𝗧𝗘 💎 ˎˊ-\n"
                  f"╚═════════════════════════════╝\n\n"
                  f" »» Join »» t.me/team_falcone «« Join ««\n"
                  f"```")
    await user.send_message(chat_id=TARGET_GROUP, text=promo_text, parse_mode=ParseMode.MARKDOWN)
    logger.info("✅ Promotional message sent.")

#@diwazz
async def get_all_groups_and_channels():
    groups = []
    async for dialog in user.get_dialogs():
        if dialog.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL} and dialog.chat.id != TARGET_GROUP:
            groups.append({'id': dialog.chat.id, 'title': dialog.chat.title})
    return groups

async def join_target_group():
    try:
        await user.get_chat(TARGET_GROUP)
        logger.info("✅ Already in the target group.")
        return True
    except Exception:
        logger.info(f"⚠️ Not in target group {TARGET_GROUP}. Attempting to join via invite link...")
        invite_link = "https://t.me/+0ZiC00eC5QJkYjJl"
        try:
            await user.join_chat(invite_link)
            logger.info("✅ Successfully joined target group!")
            return True
        except UserAlreadyParticipant:
             logger.info("✅ Already a member of target group (confirmed after join attempt).")
             return True
        except (InviteHashExpired, InviteHashInvalid) as e:
            logger.error(f"❌ Failed to join target group: Invite link is invalid or expired ({type(e).__name__})")
            return False
        except Exception as e:
            logger.error(f"❌ An unexpected error occurred while joining: {e}")
            return False

#@diwazz
async def handle_health_check(request):
    return web.Response(text="OK: Bot is running.")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get('PORT', 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"🌐 Anti-sleep web server started on port {port}.")

def signal_handler(signum, frame):
    global is_running
    logger.info("🛑 Shutdown signal received. Gracefully stopping...")
    is_running = False
    for task in asyncio.all_tasks(): task.cancel()

async def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        await user.start()
        me = await user.get_me()
        logger.info(f"👤 Logged in as: {me.first_name} (@{me.username})")

        if not await join_target_group():
            logger.error("❌ Cannot proceed without access to the target group.")
            await user.stop()
            return

        #diwazz
        scheduler = AsyncIOScheduler(timezone=str(pytz.utc))
        scheduler.add_job(send_hourly_report, 'interval', hours=1)
        scheduler.add_job(send_promo_message, 'interval', minutes=30)
        scheduler.start()
        logger.info("⏰ Scheduled tasks are now active.")

        await asyncio.gather(
            poll_all_groups(),
            start_web_server()
        )

    except asyncio.CancelledError:
        logger.info("Main task cancelled.")
    except Exception as e:
        logger.error(f"An error occurred in main: {e}")
    finally:
        if user.is_connected:
            await user.stop()
        logger.info("✅ Client stopped cleanly.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 Process stopped by user.")
