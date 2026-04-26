"""
РЕМОНТ.APP — CustDev Bot (PostgreSQL version for Railway)
"""

import logging
import asyncio
import csv
import io
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    BufferedInputFile
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

import asyncpg

# ── CONFIG ────────────────────────────────────────────────────────────────────
BOT_TOKEN   = os.getenv("BOT_TOKEN", "")
ADMIN_IDS   = [int(x) for x in os.getenv("ADMIN_IDS", "0").split(",") if x.strip().isdigit()]
DATABASE_URL = os.getenv("DATABASE_URL", "")  # Railway auto-injects this

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# ── STATES ────────────────────────────────────────────────────────────────────
class Interview(StatesGroup):
    q1_city         = State()
    q2_area         = State()
    q3_budget       = State()
    q4_overspend    = State()
    q5_duration     = State()
    q6_overdue      = State()
    q7_biggest_pain = State()
    q8_contractor   = State()
    q9_trust        = State()
    q10_materials   = State()
    q11_smeta       = State()
    q12_wish        = State()
    q13_tool        = State()
    q14_nps         = State()
    done            = State()

# ── QUESTIONS ─────────────────────────────────────────────────────────────────
QUESTIONS = {
    "q1_city": {
        "text": (
            "Привет! Я помогаю сделать ремонт в России лучше — собираю реальный опыт людей, "
            "которые уже через это прошли.\n\nЭто займёт ~5 минут. Всё анонимно.\n\n"
            "Начнём! В каком городе вы делали ремонт?"
        ),
        "type": "choice",
        "options": ["Москва", "Санкт-Петербург", "Другой город-миллионник", "Город < 1 млн"],
    },
    "q2_area": {
        "text": "Какая площадь квартиры?",
        "type": "choice",
        "options": ["До 40 м²", "40–65 м²", "65–100 м²", "Более 100 м²"],
    },
    "q3_budget": {
        "text": "Какой бюджет вы планировали на ремонт изначально?",
        "type": "choice",
        "options": ["До 500 тыс. ₽", "500 тыс. – 1,5 млн ₽", "1,5 – 3 млн ₽", "Более 3 млн ₽"],
    },
    "q4_overspend": {
        "text": "Вышли ли вы за первоначальный бюджет?",
        "type": "choice",
        "options": ["Нет, уложились", "Вышли на 10–20%", "Вышли на 20–50%", "Вышли более чем на 50%"],
    },
    "q5_duration": {
        "text": "Сколько по факту длился ремонт?",
        "type": "choice",
        "options": ["До 2 месяцев", "2–4 месяца", "4–8 месяцев", "Более 8 месяцев"],
    },
    "q6_overdue": {
        "text": "Подрядчики задержали срок сдачи?",
        "type": "choice",
        "options": ["Нет, сдали вовремя", "Задержали до 1 месяца", "Задержали 1–3 месяца", "Задержали более 3 месяцев"],
    },
    "q7_biggest_pain": {
        "text": (
            "Вот главный вопрос!\n\n"
            "Что было самым неприятным, стрессовым или дорогостоящим в процессе ремонта? "
            "Напишите своими словами — это очень важно"
        ),
        "type": "free",
    },
    "q8_contractor": {
        "text": "Как вы искали подрядчиков (прораба, бригаду)?",
        "type": "choice",
        "options": ["По рекомендации друзей/знакомых", "Авито / YouDo / профильные сайты", "Дизайнер привёл своих", "Застройщик предложил"],
    },
    "q9_trust": {
        "text": "Насколько вы доверяли своему подрядчику в процессе ремонта?\n\n1 — совсем не доверял(а), 5 — полное доверие",
        "type": "choice",
        "options": ["1 — совсем не доверял", "2", "3 — средне", "4", "5 — полное доверие"],
    },
    "q10_materials": {
        "text": "Где вы покупали большинство материалов и мебели?",
        "type": "choice",
        "options": ["Леруа Мерлен / OBI", "IKEA / онлайн-мебель", "Строительные рынки", "Смешанно: онлайн + офлайн"],
    },
    "q11_smeta": {
        "text": "Как вы составляли смету на ремонт?",
        "type": "choice",
        "options": ["Подрядчик составил сам", "Excel/Google Таблицы сам(а)", "Через дизайнера", "Никак — считали по ходу"],
    },
    "q12_wish": {
        "text": (
            "Если бы вы могли изменить одну вещь в процессе ремонта — что бы это было?\n\n"
            "Напишите честно, это самый важный вопрос"
        ),
        "type": "free",
    },
    "q13_tool": {
        "text": "Какой инструмент или сервис сильно помог бы вам во время ремонта?",
        "type": "choice",
        "options": [
            "Приложение с точной сметой и контролем бюджета",
            "Проверенная база подрядчиков с отзывами",
            "3D-визуализация до начала работ",
            "Сервис контроля сроков и качества работ",
        ],
    },
    "q14_nps": {
        "text": "И последнее: вы бы порекомендовали своего прораба/бригаду друзьям?",
        "type": "choice",
        "options": ["Да, однозначно", "Скорее да", "Скорее нет", "Нет, никогда"],
    },
}

QUESTION_ORDER = [
    "q1_city", "q2_area", "q3_budget", "q4_overspend",
    "q5_duration", "q6_overdue", "q7_biggest_pain", "q8_contractor",
    "q9_trust", "q10_materials", "q11_smeta", "q12_wish",
    "q13_tool", "q14_nps",
]

STATE_MAP = {
    "q1_city":         Interview.q1_city,
    "q2_area":         Interview.q2_area,
    "q3_budget":       Interview.q3_budget,
    "q4_overspend":    Interview.q4_overspend,
    "q5_duration":     Interview.q5_duration,
    "q6_overdue":      Interview.q6_overdue,
    "q7_biggest_pain": Interview.q7_biggest_pain,
    "q8_contractor":   Interview.q8_contractor,
    "q9_trust":        Interview.q9_trust,
    "q10_materials":   Interview.q10_materials,
    "q11_smeta":       Interview.q11_smeta,
    "q12_wish":        Interview.q12_wish,
    "q13_tool":        Interview.q13_tool,
    "q14_nps":         Interview.q14_nps,
}

# ── DB POOL ───────────────────────────────────────────────────────────────────
pool: asyncpg.Pool = None

async def init_db():
    global pool
    # Railway injects DATABASE_URL as postgres://, asyncpg needs postgresql://
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    pool = await asyncpg.create_pool(url, min_size=1, max_size=5)
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS interviews (
                id              SERIAL PRIMARY KEY,
                user_id         BIGINT NOT NULL,
                username        TEXT,
                started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                finished_at     TIMESTAMPTZ,
                q1_city         TEXT,
                q2_area         TEXT,
                q3_budget       TEXT,
                q4_overspend    TEXT,
                q5_duration     TEXT,
                q6_overdue      TEXT,
                q7_biggest_pain TEXT,
                q8_contractor   TEXT,
                q9_trust        TEXT,
                q10_materials   TEXT,
                q11_smeta       TEXT,
                q12_wish        TEXT,
                q13_tool        TEXT,
                q14_nps         TEXT
            )
        """)
    log.info("PostgreSQL pool ready")

async def upsert_interview(user_id: int, username, **fields):
    async with pool.acquire() as conn:
        # Check if an open interview exists
        row = await conn.fetchrow(
            "SELECT id FROM interviews WHERE user_id=$1 AND finished_at IS NULL",
            user_id
        )
        if row:
            # Build UPDATE using column names directly in SQL (safe — not user input)
            # Pass all values as strings to avoid type inference issues
            for col, val in fields.items():
                await conn.execute(
                    f"UPDATE interviews SET {col} = $1::text WHERE user_id = $2 AND finished_at IS NULL",
                    str(val), user_id
                )
        else:
            await conn.execute("""
                INSERT INTO interviews (
                    user_id, username,
                    q1_city, q2_area, q3_budget, q4_overspend,
                    q5_duration, q6_overdue, q7_biggest_pain, q8_contractor,
                    q9_trust, q10_materials, q11_smeta, q12_wish,
                    q13_tool, q14_nps
                ) VALUES (
                    $1, $2::text,
                    $3::text, $4::text, $5::text, $6::text,
                    $7::text, $8::text, $9::text, $10::text,
                    $11::text, $12::text, $13::text, $14::text,
                    $15::text, $16::text
                )
                ON CONFLICT DO NOTHING
            """,
                               user_id, str(username) if username else None,
                               fields.get("q1_city"), fields.get("q2_area"),
                               fields.get("q3_budget"), fields.get(
                                   "q4_overspend"),
                               fields.get("q5_duration"), fields.get(
                                   "q6_overdue"),
                               fields.get("q7_biggest_pain"), fields.get(
                                   "q8_contractor"),
                               fields.get("q9_trust"), fields.get(
                                   "q10_materials"),
                               fields.get("q11_smeta"), fields.get("q12_wish"),
                               fields.get("q13_tool"), fields.get("q14_nps"),
            )

async def finish_interview(user_id: int):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE interviews SET finished_at=NOW() WHERE user_id=$1 AND finished_at IS NULL",
            user_id
        )

async def get_all_csv() -> bytes:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM interviews ORDER BY id")
    if not rows:
        return b"No data yet"
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    for row in rows:
        writer.writerow(dict(row))
    return output.getvalue().encode("utf-8-sig")

async def get_stats() -> dict:
    async with pool.acquire() as conn:
        total    = await conn.fetchval("SELECT COUNT(*) FROM interviews")
        finished = await conn.fetchval("SELECT COUNT(*) FROM interviews WHERE finished_at IS NOT NULL")
    return {"total": total, "finished": finished, "in_progress": total - finished}

# ── HELPERS ───────────────────────────────────────────────────────────────────
def make_keyboard(options, q_key) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=opt, callback_data=f"{q_key}:{i}")]
        for i, opt in enumerate(options)
    ])

def progress_bar(current: int, total: int) -> str:
    filled = round(current / total * 10)
    return f"[{'▓' * filled}{'░' * (10 - filled)}] {current}/{total}"

async def send_question(message: Message, state: FSMContext, q_key: str):
    q = QUESTIONS[q_key]
    idx = QUESTION_ORDER.index(q_key)
    text = f"{progress_bar(idx + 1, len(QUESTION_ORDER))}\n\n{q['text']}"
    await state.set_state(STATE_MAP[q_key])
    if q["type"] == "choice":
        await message.answer(text, reply_markup=make_keyboard(q["options"], q_key))
    else:
        await message.answer(text)

# ── HANDLERS ──────────────────────────────────────────────────────────────────
bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await send_question(message, state, "q1_city")

@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Интервью прервано. Напишите /start чтобы начать заново.")

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    s = await get_stats()
    pct = round(s["finished"] / s["total"] * 100) if s["total"] else 0
    await message.answer(
        f"Статистика\n\n"
        f"Всего начали: {s['total']}\n"
        f"Завершили: {s['finished']}\n"
        f"В процессе: {s['in_progress']}\n"
        f"Конверсия: {pct}%"
    )

@dp.message(Command("export"))
async def cmd_export(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    csv_bytes = await get_all_csv()
    filename = f"remont_custdev_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    await message.answer_document(
        BufferedInputFile(csv_bytes, filename=filename),
        caption="Все ответы. Открывай в Excel — кодировка UTF-8 BOM."
    )

@dp.callback_query(F.data.regexp(r"^q\d+\w*:\d+$"))
async def handle_choice(callback: CallbackQuery, state: FSMContext):
    q_key, idx_str = callback.data.rsplit(":", 1)
    q = QUESTIONS.get(q_key)
    if not q:
        return await callback.answer("Неизвестный вопрос")
    answer = q["options"][int(idx_str)]
    await callback.answer()
    user = callback.from_user
    await upsert_interview(user.id, user.username, **{q_key: answer})
    pos = QUESTION_ORDER.index(q_key)
    if pos + 1 < len(QUESTION_ORDER):
        next_key = QUESTION_ORDER[pos + 1]
        next_q = QUESTIONS[next_key]
        text = f"{progress_bar(pos + 2, len(QUESTION_ORDER))}\n\n{next_q['text']}"
        await state.set_state(STATE_MAP[next_key])
        if next_q["type"] == "choice":
            await bot.send_message(user.id, text, reply_markup=make_keyboard(next_q["options"], next_key))
        else:
            await bot.send_message(user.id, text)
    else:
        await finish_flow(callback.message, state, user)

@dp.message(Interview.q7_biggest_pain)
async def handle_q7(message: Message, state: FSMContext):
    await upsert_interview(message.from_user.id, message.from_user.username, q7_biggest_pain=message.text)
    await send_question(message, state, "q8_contractor")

@dp.message(Interview.q12_wish)
async def handle_q12(message: Message, state: FSMContext):
    await upsert_interview(message.from_user.id, message.from_user.username, q12_wish=message.text)
    await send_question(message, state, "q13_tool")

async def finish_flow(message: Message, state: FSMContext, user):
    await finish_interview(user.id)
    await state.set_state(Interview.done)
    await message.answer(
        "Готово! Спасибо за честные ответы — вы помогаете сделать ремонт в России лучше.\n\n"
        "Если захотите пройти ещё раз — /start"
    )
    s = await get_stats()
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"Новое завершённое интервью!\n"
                f"Всего завершено: {s['finished']}\n"
                f"Пользователь: @{getattr(user, 'username', None) or user.id}"
            )
        except Exception:
            pass

# ── MAIN ──────────────────────────────────────────────────────────────────────
async def main():
    await init_db()
    log.info("Bot starting...")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    asyncio.run(main())
