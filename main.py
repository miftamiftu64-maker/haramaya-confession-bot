import telebot
from telebot import types
import sqlite3
import logging
import time
import re
from datetime import datetime

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BOT_TOKEN          = '8580557776:AAEBqV6RvaXUdxYCD9khVNuckt_y-3xBmow'
CHANNEL_USERNAME   = '@HARAMAYAUNIVERSITYCONFESSIONCHAN'
DISCUSSION_GROUP   = -1003922762967
ADMIN_USER_IDS     = [1019802992, 7018551827, 7614290889]

# ─── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ─── BOT ──────────────────────────────────────────────────────────────────────
bot = telebot.TeleBot(BOT_TOKEN)
BOT_USERNAME = None  # cached on first use

def get_bot_username():
    global BOT_USERNAME
    if not BOT_USERNAME:
        BOT_USERNAME = bot.get_me().username
    return BOT_USERNAME

# ─── TAGS ─────────────────────────────────────────────────────────────────────
TAGS = [
    ('❤️', 'Love'),
    ('🎓', 'Academic'),
    ('🏛', 'University Life'),
    ('😂', 'Humor'),
    ('🤝', 'Advice'),
    ('💘', 'Romance'),
    ('😈', 'Naughty'),
    ('😍', 'Crush'),
    ('🗒', 'Other'),
]

# ─── DATABASE ─────────────────────────────────────────────────────────────────
def get_conn():
    conn = sqlite3.connect('confessions.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS pending_confessions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER,
                confession_text TEXT,
                tag             TEXT,
                timestamp       DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS user_sessions (
                user_id         INTEGER PRIMARY KEY,
                state           TEXT DEFAULT 'idle',
                temp_confession TEXT,
                commenting_on   INTEGER
            );
            CREATE TABLE IF NOT EXISTS confession_counter (
                id          INTEGER PRIMARY KEY CHECK (id = 1),
                last_number INTEGER DEFAULT 1499
            );
            CREATE TABLE IF NOT EXISTS posted_confessions (
                confession_number  INTEGER PRIMARY KEY,
                channel_msg_id     INTEGER,
                group_msg_id       INTEGER,
                confession_text    TEXT,
                tag                TEXT,
                user_id            INTEGER
            );
            CREATE TABLE IF NOT EXISTS anonymous_comments (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                confession_number  INTEGER,
                comment_text       TEXT,
                group_msg_id       INTEGER,
                timestamp          DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        conn.execute('INSERT OR IGNORE INTO confession_counter (id, last_number) VALUES (1, 1499)')
        conn.commit()

init_db()

# ─── HELPERS ──────────────────────────────────────────────────────────────────
def next_number():
    with get_conn() as conn:
        n = conn.execute('SELECT last_number FROM confession_counter WHERE id=1').fetchone()[0] + 1
        conn.execute('UPDATE confession_counter SET last_number=? WHERE id=1', (n,))
        conn.commit()
    return n

def set_state(user_id, state, confession=None, commenting_on=None):
    with get_conn() as conn:
        conn.execute(
            'INSERT OR REPLACE INTO user_sessions (user_id, state, temp_confession, commenting_on) VALUES (?,?,?,?)',
            (user_id, state, confession, commenting_on)
        )
        conn.commit()

def get_session(user_id):
    with get_conn() as conn:
        row = conn.execute('SELECT * FROM user_sessions WHERE user_id=?', (user_id,)).fetchone()
    return dict(row) if row else {'user_id': user_id, 'state': 'idle', 'temp_confession': None, 'commenting_on': None}

def save_pending(user_id, text, tag):
    with get_conn() as conn:
        cursor = conn.execute(
            'INSERT INTO pending_confessions (user_id, confession_text, tag) VALUES (?,?,?)',
            (user_id, text, tag)
        )
        conn.commit()
        return cursor.lastrowid

def get_pending(conf_id):
    with get_conn() as conn:
        row = conn.execute('SELECT * FROM pending_confessions WHERE id=?', (conf_id,)).fetchone()
    return dict(row) if row else None

def delete_pending(conf_id):
    with get_conn() as conn:
        conn.execute('DELETE FROM pending_confessions WHERE id=?', (conf_id,))
        conn.commit()

def save_posted(confession_number, channel_msg_id, group_msg_id, text, tag, user_id):
    with get_conn() as conn:
        conn.execute(
            'INSERT OR REPLACE INTO posted_confessions (confession_number, channel_msg_id, group_msg_id, confession_text, tag, user_id) VALUES (?,?,?,?,?,?)',
            (confession_number, channel_msg_id, group_msg_id, text, tag, user_id)
        )
        conn.commit()

def get_posted_by_number(number):
    with get_conn() as conn:
        row = conn.execute('SELECT * FROM posted_confessions WHERE confession_number=?', (number,)).fetchone()
    return dict(row) if row else None

def get_user_submissions(user_id):
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT * FROM posted_confessions WHERE user_id=? ORDER BY confession_number DESC LIMIT 10',
            (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]

def save_comment(confession_number, comment_text, group_msg_id):
    with get_conn() as conn:
        conn.execute(
            'INSERT INTO anonymous_comments (confession_number, comment_text, group_msg_id) VALUES (?,?,?)',
            (confession_number, comment_text, group_msg_id)
        )
        conn.commit()

def get_comments(confession_number):
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT * FROM anonymous_comments WHERE confession_number=? ORDER BY timestamp ASC',
            (confession_number,)
        ).fetchall()
    return [dict(r) for r in rows]

def get_total_confessions():
    with get_conn() as conn:
        row = conn.execute('SELECT last_number FROM confession_counter WHERE id=1').fetchone()
    return row[0] if row else 1499

# ─── SET BOT COMMANDS (shows Start button & menu) ─────────────────────────────
def set_bot_commands():
    commands = [
        types.BotCommand('start',   'Open main menu'),
        types.BotCommand('confess', 'Submit a confession'),
        types.BotCommand('comment', 'Comment on a confession'),
        types.BotCommand('submissions', 'My approved confessions'),
        types.BotCommand('help',    'How the bot works'),
    ]
    try:
        bot.set_my_commands(commands)
        logger.info("Bot commands set successfully.")
    except Exception as e:
        logger.warning(f"Could not set commands: {e}")

# ─── KEYBOARDS ────────────────────────────────────────────────────────────────
def main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    markup.add(
        types.KeyboardButton('📝 Confess'),
        types.KeyboardButton('💬 Comment'),
        types.KeyboardButton('ℹ️ Help')
    )
    markup.add(types.KeyboardButton('📜 My Submissions'))
    return markup

def tag_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    buttons = [types.KeyboardButton(f"{emoji} {name}") for emoji, name in TAGS]
    markup.add(*buttons)
    markup.add(types.KeyboardButton('❌ Cancel'))
    return markup

def cancel_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton('❌ Cancel'))
    return markup

def post_buttons(confession_number):
    """Inline buttons shown on every channel post: Comment + Add Post"""
    uname = get_bot_username()
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(
            "💬 Comment Anonymously",
            url=f"https://t.me/{uname}?start=comment_{confession_number}"
        ),
        types.InlineKeyboardButton(
            "📝 Add Post",
            url=f"https://t.me/{uname}?start=confess"
        )
    )
    markup.add(
        types.InlineKeyboardButton(
            "👁 View Comments",
            url=f"https://t.me/{uname}?start=viewcomments_{confession_number}"
        )
    )
    return markup

def comments_nav_keyboard(conf_num, page, total_pages):
    """Navigation keyboard for browsing comments page by page"""
    markup = types.InlineKeyboardMarkup(row_width=3)
    buttons = []
    if page > 0:
        buttons.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"cmtpage:{conf_num}:{page-1}"))
    buttons.append(types.InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        buttons.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"cmtpage:{conf_num}:{page+1}"))
    markup.add(*buttons)
    markup.add(types.InlineKeyboardButton("💬 Add Comment", callback_data=f"addcomment:{conf_num}"))
    return markup

# ─── SHOW COMMENTS PAGE ───────────────────────────────────────────────────────
COMMENTS_PER_PAGE = 5

def show_comments_page(chat_id, conf_num, page, message_id=None):
    posted = get_posted_by_number(conf_num)
    if not posted:
        bot.send_message(chat_id, f"❌ Confession #{conf_num} not found.", reply_markup=main_keyboard())
        return

    comments = get_comments(conf_num)
    total = len(comments)

    if total == 0:
        text = (
            f"💬 Comments for Confession #{conf_num}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏷 {posted['tag']}\n\n"
            f"No comments yet. Be the first to comment! 👇"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💬 Add Comment", callback_data=f"addcomment:{conf_num}"))
        if message_id:
            try:
                bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            except Exception:
                bot.send_message(chat_id, text, reply_markup=markup)
        else:
            bot.send_message(chat_id, text, reply_markup=markup)
        return

    total_pages = max(1, (total + COMMENTS_PER_PAGE - 1) // COMMENTS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * COMMENTS_PER_PAGE
    slice_ = comments[start:start + COMMENTS_PER_PAGE]

    confession_preview = posted['confession_text'][:100] + ('…' if len(posted['confession_text']) > 100 else '')
    text = (
        f"💬 Comments for Confession #{conf_num}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏷 {posted['tag']}\n"
        f"{confession_preview}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Total: {total} comment(s)  •  Page {page+1}/{total_pages}\n\n"
    )
    for i, c in enumerate(slice_, start=start+1):
        text += f"[{i}] {c['comment_text']}\n\n"

    markup = comments_nav_keyboard(conf_num, page, total_pages)

    if message_id:
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
        except Exception:
            bot.send_message(chat_id, text, reply_markup=markup)
    else:
        bot.send_message(chat_id, text, reply_markup=markup)

# ─── /start ───────────────────────────────────────────────────────────────────
@bot.message_handler(commands=['start'])
def cmd_start(message):
    args = message.text.split()

    # Deep link: comment on a specific confession
    if len(args) > 1 and args[1].startswith('comment_'):
        try:
            conf_num = int(args[1].split('_')[1])
            ask_for_comment(message.chat.id, message.from_user.id, conf_num)
            return
        except Exception:
            pass

    # Deep link: view comments of a specific confession
    if len(args) > 1 and args[1].startswith('viewcomments_'):
        try:
            conf_num = int(args[1].split('_')[1])
            set_state(message.from_user.id, 'idle')
            show_comments_page(message.chat.id, conf_num, 0)
            return
        except Exception:
            pass

    # Deep link: open confess directly
    if len(args) > 1 and args[1] == 'confess':
        set_state(message.from_user.id, 'awaiting_confession')
        bot.send_message(
            message.chat.id,
            "📝 Write your confession below and send it:\n\n🔒 Your identity will never be revealed",
            reply_markup=cancel_keyboard()
        )
        return

    set_state(message.from_user.id, 'idle')
    first_name = message.from_user.first_name or 'there'
    bot.send_message(
        message.chat.id,
        f"👋 Hey {first_name}! Welcome to Haramaya Confession Bot\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🔒 100% Anonymous — no one will ever know who you are\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📝 Confess — Share your thoughts anonymously\n"
        "💬 Comment — Comment on any confession\n"
        "👁 View Comments — Browse comments on any post\n"
        "📜 My Submissions — See your approved confessions\n"
        "ℹ️ Help — How the bot works\n\n"
        "Choose an option from the menu below 👇",
        reply_markup=main_keyboard()
    )

# ─── COMMANDS shortcut ────────────────────────────────────────────────────────
@bot.message_handler(commands=['confess'])
def cmd_confess(message):
    set_state(message.from_user.id, 'awaiting_confession')
    bot.send_message(
        message.chat.id,
        "📝 Write your confession below and send it:\n\n🔒 Your identity will never be revealed",
        reply_markup=cancel_keyboard()
    )

@bot.message_handler(commands=['comment'])
def cmd_comment(message):
    set_state(message.from_user.id, 'awaiting_comment_number')
    bot.send_message(
        message.chat.id,
        "💬 Anonymous Comment\n\nEnter the confession number you want to comment on:\nExample: 1500",
        reply_markup=cancel_keyboard()
    )

@bot.message_handler(commands=['submissions'])
def cmd_submissions(message):
    my_submissions(message)

@bot.message_handler(commands=['help'])
def cmd_help(message):
    show_help(message)

# ─── HELP ─────────────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == 'ℹ️ Help')
def show_help(message):
    total = get_total_confessions() - 1499
    bot.send_message(
        message.chat.id,
        "ℹ️ How it works\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📝 Submitting a Confession\n"
        "1. Tap Confess\n"
        "2. Write your confession\n"
        "3. Choose a tag\n"
        "4. Wait for admin approval\n"
        "5. Posted anonymously!\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💬 Commenting\n"
        "1. Tap Comment or tap the button under any channel post\n"
        "2. Enter the confession number\n"
        "3. Write your comment — posted anonymously!\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "👁 View Comments\n"
        "Tap View Comments under any channel post\n"
        "or use the Comment button in the bot menu\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Total confessions posted: {total}\n"
        "🔒 Your identity is always 100% protected",
        reply_markup=main_keyboard()
    )

# ─── MY SUBMISSIONS ───────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == '📜 My Submissions')
def my_submissions(message):
    submissions = get_user_submissions(message.from_user.id)
    if not submissions:
        bot.send_message(
            message.chat.id,
            "📜 You haven't had any confessions approved yet.\n\nTap 📝 Confess to submit your first one!",
            reply_markup=main_keyboard()
        )
        return

    text = "📜 Your Approved Confessions (latest 10)\n\n"
    for s in submissions:
        preview = s['confession_text'][:80] + ('…' if len(s['confession_text']) > 80 else '')
        comments = get_comments(s['confession_number'])
        text += f"#{s['confession_number']} {s['tag']}\n{preview}\n💬 {len(comments)} comment(s)\n\n"

    bot.send_message(message.chat.id, text, reply_markup=main_keyboard())

# ─── CONFESS — STEP 1 ─────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == '📝 Confess')
def prompt_confession(message):
    set_state(message.from_user.id, 'awaiting_confession')
    bot.send_message(
        message.chat.id,
        "📝 Write your confession below and send it:\n\n🔒 Your identity will never be revealed",
        reply_markup=cancel_keyboard()
    )

# ─── CONFESS — STEP 2: receive text ───────────────────────────────────────────
@bot.message_handler(func=lambda m: get_session(m.from_user.id).get('state') == 'awaiting_confession',
                     content_types=['text'])
def receive_confession(message):
    session = get_session(message.from_user.id)
    if session.get('state') != 'awaiting_confession':
        return

    if message.text == '❌ Cancel':
        set_state(message.from_user.id, 'idle')
        bot.send_message(message.chat.id, "❌ Cancelled.", reply_markup=main_keyboard())
        return

    text = message.text.strip()
    if len(text) < 5:
        bot.send_message(message.chat.id, "❌ Too short. Please write at least 5 characters.")
        return
    if len(text) > 2000:
        bot.send_message(message.chat.id, "❌ Too long! Keep it under 2000 characters.")
        return

    set_state(message.from_user.id, 'awaiting_tag', confession=text)
    bot.send_message(message.chat.id, "🏷 Now choose a tag for your confession:", reply_markup=tag_keyboard())

# ─── CONFESS — STEP 3: receive tag ────────────────────────────────────────────
@bot.message_handler(func=lambda m: get_session(m.from_user.id).get('state') == 'awaiting_tag',
                     content_types=['text'])
def receive_tag(message):
    session = get_session(message.from_user.id)
    if session.get('state') != 'awaiting_tag':
        return

    if message.text == '❌ Cancel':
        set_state(message.from_user.id, 'idle')
        bot.send_message(message.chat.id, "❌ Cancelled.", reply_markup=main_keyboard())
        return

    selected_tag = None
    msg_text = message.text.strip()
    for emoji, name in TAGS:
        full = f"{emoji} {name}"
        if msg_text == full or msg_text == name or name in msg_text:
            selected_tag = full
            break

    if not selected_tag:
        bot.send_message(message.chat.id, "❌ Please select a tag from the buttons below.", reply_markup=tag_keyboard())
        return

    confession_text = session.get('temp_confession')
    if not confession_text:
        set_state(message.from_user.id, 'idle')
        bot.send_message(message.chat.id, "❌ Session expired. Please start over.", reply_markup=main_keyboard())
        return

    num = next_number()
    channel_text = f"{selected_tag}\n\n{confession_text}\n\n#{num}\n#HaramayaConfessions"
    set_state(message.from_user.id, 'idle')
    try:
        channel_msg = bot.send_message(
            CHANNEL_USERNAME,
            channel_text,
            reply_markup=post_buttons(num)
        )
        group_msg = bot.send_message(
            DISCUSSION_GROUP,
            f"💬 Comments for Confession #{num}\n\nTap below to comment anonymously 👇",
            reply_markup=post_buttons(num)
        )
        save_posted(num, channel_msg.message_id, group_msg.message_id, confession_text, selected_tag, message.from_user.id)
        bot.send_message(
            message.chat.id,
            f"✅ Confession Posted!\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏷 Tag: {selected_tag}\n"
            f"Posted as #{num}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Thank you for sharing 💙",
            reply_markup=main_keyboard()
        )
    except Exception as e:
        bot.send_message(message.chat.id, "❌ Failed to post. Please try again.", reply_markup=main_keyboard())
        logger.error(f"Auto post failed: {e}")

# ─── COMMENT ──────────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == '💬 Comment')
def prompt_comment_number(message):
    set_state(message.from_user.id, 'awaiting_comment_number')
    bot.send_message(
        message.chat.id,
        "💬 Anonymous Comment\n\nEnter the confession number you want to comment on:\nExample: 1500",
        reply_markup=cancel_keyboard()
    )

@bot.message_handler(func=lambda m: get_session(m.from_user.id).get('state') == 'awaiting_comment_number',
                     content_types=['text'])
def receive_comment_number(message):
    session = get_session(message.from_user.id)
    if session.get('state') != 'awaiting_comment_number':
        return

    if message.text == '❌ Cancel':
        set_state(message.from_user.id, 'idle')
        bot.send_message(message.chat.id, "❌ Cancelled.", reply_markup=main_keyboard())
        return

    try:
        conf_num = int(message.text.strip().replace('#', ''))
    except ValueError:
        bot.send_message(message.chat.id, "❌ Please enter a valid number like 1500")
        return

    ask_for_comment(message.chat.id, message.from_user.id, conf_num)

def ask_for_comment(chat_id, user_id, conf_num):
    posted = get_posted_by_number(conf_num)
    if not posted:
        bot.send_message(chat_id, f"❌ Confession #{conf_num} not found. Check the number and try again.", reply_markup=main_keyboard())
        set_state(user_id, 'idle')
        return

    comments = get_comments(conf_num)
    preview = posted['confession_text'][:200] + ('…' if len(posted['confession_text']) > 200 else '')

    bot.send_message(
        chat_id,
        f"💬 Commenting on Confession #{conf_num}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏷 {posted['tag']}\n\n"
        f"{preview}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💬 {len(comments)} comment(s) so far\n\n"
        f"Write your comment below 👇",
        reply_markup=cancel_keyboard()
    )
    set_state(user_id, 'awaiting_comment', commenting_on=conf_num)

@bot.message_handler(func=lambda m: get_session(m.from_user.id).get('state') == 'awaiting_comment',
                     content_types=['text'])
def receive_comment(message):
    session = get_session(message.from_user.id)
    if session.get('state') != 'awaiting_comment':
        return

    if message.text == '❌ Cancel':
        set_state(message.from_user.id, 'idle')
        bot.send_message(message.chat.id, "❌ Cancelled.", reply_markup=main_keyboard())
        return

    comment_text = message.text.strip()
    conf_num = session.get('commenting_on')

    if not conf_num:
        set_state(message.from_user.id, 'idle')
        bot.send_message(message.chat.id, "❌ Something went wrong. Please try again.", reply_markup=main_keyboard())
        return
    if len(comment_text) < 2:
        bot.send_message(message.chat.id, "❌ Comment is too short.")
        return
    if len(comment_text) > 1000:
        bot.send_message(message.chat.id, "❌ Too long! Keep it under 1000 characters.")
        return

    posted = get_posted_by_number(conf_num)
    if not posted:
        set_state(message.from_user.id, 'idle')
        bot.send_message(message.chat.id, "❌ Confession not found.", reply_markup=main_keyboard())
        return

    set_state(message.from_user.id, 'idle')

    try:
        sent = bot.send_message(
            DISCUSSION_GROUP,
            f"💬 Anonymous Comment on #{conf_num}:\n\n{comment_text}",
            reply_to_message_id=posted['group_msg_id']
        )
        save_comment(conf_num, comment_text, sent.message_id)

        # After posting, show the updated comments with nav buttons
        bot.send_message(
            message.chat.id,
            f"✅ Comment Posted!\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Your anonymous comment on confession #{conf_num} is now live!\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔒 Nobody knows it was you\n\n"
            f"Tap below to see all comments 👇",
            reply_markup=main_keyboard()
        )
        # Show comments viewer right after
        show_comments_page(message.chat.id, conf_num, 999)  # 999 = last page

    except Exception as e:
        logger.error(f"Failed to post comment: {e}")
        bot.send_message(message.chat.id, "❌ Failed to post comment. Please try again.", reply_markup=main_keyboard())

# ─── INLINE BUTTON: page comments ─────────────────────────────────────────────
@bot.callback_query_handler(func=lambda call: call.data.startswith('cmtpage:'))
def handle_comment_page(call):
    try:
        parts = call.data.split(':')
        conf_num = int(parts[1])
        page = int(parts[2])
        show_comments_page(call.message.chat.id, conf_num, page, call.message.message_id)
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Error handling comment page: {e}")
        bot.answer_callback_query(call.id, "Error loading page", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith('addcomment:'))
def handle_add_comment_button(call):
    try:
        conf_num = int(call.data.split(':')[1])
        ask_for_comment(call.message.chat.id, call.from_user.id, conf_num)
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Error handling add comment: {e}")
        bot.answer_callback_query(call.id, "Error", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data == 'noop')
def handle_noop(call):
    bot.answer_callback_query(call.id)

# ─── ADMIN: approve & post ────────────────────────────────────────────────────
def send_to_admins(conf_id, user_id, text, tag):
    """Send pending confession to admins for approval (legacy, not used with auto-post)"""
    pending = get_pending(conf_id)
    if not pending:
        return

    for admin_id in ADMIN_USER_IDS:
        try:
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("✅ Approve", callback_data=f"approve:{conf_id}"),
                types.InlineKeyboardButton("❌ Reject", callback_data=f"reject:{conf_id}")
            )
            bot.send_message(
                admin_id,
                f"📝 New Confession Pending Approval\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🏷 Tag: {tag}\n"
                f"👤 User ID: {user_id}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{text}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━",
                reply_markup=markup
            )
        except Exception as e:
            logger.error(f"Failed to send to admin {admin_id}: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('approve:'))
def handle_approve(call):
    try:
        conf_id = int(call.data.split(':')[1])
        pending = get_pending(conf_id)
        if not pending:
            bot.answer_callback_query(call.id, "Confession not found", show_alert=True)
            return

        num = next_number()
        channel_text = f"{pending['tag']}\n\n{pending['confession_text']}\n\n#{num}\n#HaramayaConfessions"

        channel_msg = bot.send_message(
            CHANNEL_USERNAME,
            channel_text,
            reply_markup=post_buttons(num)
        )
        group_msg = bot.send_message(
            DISCUSSION_GROUP,
            f"💬 Comments for Confession #{num}\n\nTap below to comment anonymously 👇",
            reply_markup=post_buttons(num)
        )
        save_posted(num, channel_msg.message_id, group_msg.message_id, pending['confession_text'], pending['tag'], pending['user_id'])
        delete_pending(conf_id)

        bot.edit_message_text(
            f"✅ Approved & Posted as #{num}",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id
        )
        bot.answer_callback_query(call.id, "Approved!", show_alert=False)

        try:
            bot.send_message(
                pending['user_id'],
                f"✅ Your confession was approved!\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🏷 Tag: {pending['tag']}\n"
                f"Posted as #{num}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"Thank you for sharing 💙",
                reply_markup=main_keyboard()
            )
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Error approving confession: {e}")
        bot.answer_callback_query(call.id, "Error approving", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith('reject:'))
def handle_reject(call):
    try:
        conf_id = int(call.data.split(':')[1])
        pending = get_pending(conf_id)
        if not pending:
            bot.answer_callback_query(call.id, "Confession not found", show_alert=True)
            return

        delete_pending(conf_id)
        bot.edit_message_text(
            "❌ Rejected",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id
        )
        bot.answer_callback_query(call.id, "Rejected", show_alert=False)

        try:
            bot.send_message(
                pending['user_id'],
                "❌ Your confession was rejected by admins.\n\n"
                "Please review our community guidelines and try again.",
                reply_markup=main_keyboard()
            )
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Error rejecting confession: {e}")
        bot.answer_callback_query(call.id, "Error rejecting", show_alert=True)

# ─── POLLING ──────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    set_bot_commands()
    logger.info("Bot started. Polling...")
    try:
        bot.infinity_polling()
    except Exception as e:
        logger.error(f"Bot error: {e}")

