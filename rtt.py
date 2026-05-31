import telebot
from telebot import types
import sqlite3
import logging
import time
from datetime datetime

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BOT_TOKEN          = '8580557776:AAEBqV6RvaXUdxYCD9khVNuckt_y-3xBmow'
CHANNEL_USERNAME   = '@HARAMAYAUNIVERSITYCONFESSIONCHAN'
DISCUSSION_GROUP   = -1003922762967
ADMIN_USER_IDS     = [1019802992, 7018551827, 7614290889]

# Set to True to skip admin approval (for testing)
AUTO_APPROVE = True

# ─── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ─── BOT ──────────────────────────────────────────────────────────────────────
bot = telebot.TeleBot(BOT_TOKEN)

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
    
    if row:
        return dict(row)
    else:
        return {
            'user_id': user_id,
            'state': 'idle', 
            'temp_confession': None, 
            'commenting_on': None
        }

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

# ─── KEYBOARDS ────────────────────────────────────────────────────────────────
def main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    markup.add(
        types.KeyboardButton('📝 Confess'),
        types.KeyboardButton('💬 Comment'),
        types.KeyboardButton('ℹ️ Help')
    )
    markup.add(
        types.KeyboardButton('📜 My Submissions')
    )
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

def make_comment_button(confession_number):
    markup = types.InlineKeyboardMarkup()
    try:
        bot_user = bot.get_me()
        bot_username = bot_user.username
        url = f"https://t.me/{bot_username}?start=comment_{confession_number}"
        markup.add(types.InlineKeyboardButton("💬 Comment Anonymously", url=url))
    except:
        markup.add(types.InlineKeyboardButton("💬 Comment Anonymously", url=f"https://t.me/HU_CONFESSOR_BOT?start=comment_{confession_number}"))
    return markup

def auto_approve_confession(user_id, text, tag):
    num = next_number()
    channel_text = f"{tag}\n\n{text}\n\n#{num}\n#HaramayaConfessions"

    try:
        channel_msg = bot.send_message(
            CHANNEL_USERNAME,
            channel_text,
            reply_markup=make_comment_button(num),
            parse_mode='HTML'
        )
        group_msg = bot.send_message(
            DISCUSSION_GROUP,
            f"💬 *Comments for Confession #{num}*\n\nTap below to comment anonymously 👇\n\nhttps://t.me/{bot.get_me().username}?start=comment_{num}",
            parse_mode='Markdown'
        )
        save_posted(num, channel_msg.message_id, group_msg.message_id, text, tag, user_id)
        
        bot.send_message(
            user_id,
            f"🎉 *Confession Posted!*\n\nYour confession was posted as *#{num}*\n\nThank you for sharing! 💙",
            parse_mode='Markdown',
            reply_markup=main_keyboard()
        )
        return True
    except Exception as e:
        logger.error(f"Failed to post: {e}")
        bot.send_message(user_id, f"❌ Error: {e}")
        return False

# ─── /start ───────────────────────────────────────────────────────────────────
@bot.message_handler(commands=['start'])
def cmd_start(message):
    args = message.text.split()
    if len(args) > 1 and args[1].startswith('comment_'):
        try:
            conf_num = int(args[1].split('_')[1])
            ask_for_comment(message.chat.id, message.from_user.id, conf_num)
            return
        except Exception:
            pass

    set_state(message.from_user.id, 'idle')
    bot.send_message(
        message.chat.id,
        f"👋 Welcome! Send /help for instructions",
        reply_markup=main_keyboard()
    )

@bot.message_handler(func=lambda m: m.text == '📝 Confess')
def prompt_confession(message):
    set_state(message.from_user.id, 'awaiting_confession')
    bot.send_message(
        message.chat.id,
        "📝 Write your confession below:",
        reply_markup=cancel_keyboard()
    )

@bot.message_handler(func=lambda m: get_session(m.from_user.id).get('state') == 'awaiting_confession')
def receive_confession(message):
    if message.text == '❌ Cancel':
        set_state(message.from_user.id, 'idle')
        bot.send_message(message.chat.id, "Cancelled.", reply_markup=main_keyboard())
        return

    text = message.text.strip()
    if len(text) < 5:
        bot.send_message(message.chat.id, "Too short. Try again.")
        return

    set_state(message.from_user.id, 'awaiting_tag', confession=text)
    bot.send_message(message.chat.id, "Choose a tag:", reply_markup=tag_keyboard())

@bot.message_handler(func=lambda m: get_session(m.from_user.id).get('state') == 'awaiting_tag')
def receive_tag(message):
    if message.text == '❌ Cancel':
        set_state(message.from_user.id, 'idle')
        bot.send_message(message.chat.id, "Cancelled.", reply_markup=main_keyboard())
        return

    session = get_session(message.from_user.id)
    selected_tag = None
    
    for emoji, name in TAGS:
        if message.text == f"{emoji} {name}":
            selected_tag = f"{emoji} {name}"
            break

    if not selected_tag:
        bot.send_message(message.chat.id, "Please use the buttons below.", reply_markup=tag_keyboard())
        return

    confession_text = session.get('temp_confession')
    set_state(message.from_user.id, 'idle')
    
    bot.send_message(message.chat.id, "Posting your confession...", reply_markup=main_keyboard())
    auto_approve_confession(message.from_user.id, confession_text, selected_tag)

def ask_for_comment(chat_id, user_id, conf_num):
    posted = get_posted_by_number(conf_num)
    if not posted:
        bot.send_message(chat_id, f"❌ Confession #{conf_num} not found.")
        return

    set_state(user_id, 'awaiting_comment', commenting_on=conf_num)
    bot.send_message(chat_id, f"💬 Write your comment for #{conf_num}:", reply_markup=cancel_keyboard())

@bot.message_handler(func=lambda m: get_session(m.from_user.id).get('state') == 'awaiting_comment')
def receive_comment(message):
    if message.text == '❌ Cancel':
        set_state(message.from_user.id, 'idle')
        bot.send_message(message.chat.id, "Cancelled.", reply_markup=main_keyboard())
        return

    session = get_session(message.from_user.id)
    conf_num = session.get('commenting_on')
    comment_text = message.text.strip()

    posted = get_posted_by_number(conf_num)
    if not posted:
        set_state(message.from_user.id, 'idle')
        bot.send_message(message.chat.id, "Confession not found.")
        return

    try:
        sent = bot.send_message(
            DISCUSSION_GROUP,
            f"💬 Comment on #{conf_num}:\n\n{comment_text}",
            reply_to_message_id=posted['group_msg_id']
        )
        save_comment(conf_num, comment_text, sent.message_id)
        set_state(message.from_user.id, 'idle')
        bot.send_message(message.chat.id, "✅ Comment posted!", reply_markup=main_keyboard())
    except Exception as e:
        bot.send_message(message.chat.id, f"Error: {e}")

if __name__ == '__main__':
    logger.info("Bot starting...")
    while True:
        try:
            bot.infinity_polling(timeout=60)
        except Exception as e:
            logger.error(f"Bot crashed: {e}. Restarting...")
            time.sleep(5)