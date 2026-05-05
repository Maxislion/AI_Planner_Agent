import asyncio
import json
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from openai import OpenAI
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os

load_dotenv()

API_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENROUTER_API_KEY")


client = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url="https://openrouter.ai/api/v1"
)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

SYSTEM_PROMPT = """
You extract tasks from user input.

Return ONLY valid JSON.
No text. No explanations.

Format:
[
  {"task": "string", "duration": number}
]

Rules:
- duration in minutes
- if not specified → 60
- output must be valid JSON
"""


def parse_tasks(text):
    response = client.chat.completions.create(
        model="openrouter/free",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text}
        ]
    )

    content = response.choices[0].message.content.strip()

    # 🔥 фикс: иногда GPT оборачивает в ```json
    if content.startswith("```"):
        content = content.split("```")[1]

    try:
        return json.loads(content)
    except:
        print("BAD RESPONSE:", content)
        return []


def to_time(t):
    return datetime.strptime(t, "%H:%M")


def to_str(t):
    return t.strftime("%H:%M")


def build_schedule(tasks):
    current_time = to_time("08:00")
    end_time = to_time("23:00")

    schedule = []

    for task in tasks:
        duration = timedelta(minutes=task["duration"])

        if current_time + duration > end_time:
            break

        schedule.append({
            "start": to_str(current_time),
            "end": to_str(current_time + duration),
            "task": task["task"]
        })

        current_time += duration + timedelta(minutes=15)

    return schedule


@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("Send your tasks")


@dp.message()
async def handle_message(message: types.Message):
    tasks = parse_tasks(message.text)

    if not tasks:
        await message.answer("Couldn't understand tasks")
        return

    schedule = build_schedule(tasks)

    result = "🗓 Plan:\n\n"
    for s in schedule:
        result += f"{s['start']} - {s['end']} | {s['task']}\n"

    await message.answer(result)


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())