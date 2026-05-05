import asyncio
import json
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from openai import OpenAI
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
from db import *

load_dotenv()

API_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENROUTER_API_KEY")
CHAT_MODEL = os.getenv("OPENROUTER_CHAT_MODEL", "openrouter/auto")


client = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url="https://openrouter.ai/api/v1"
)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

SYSTEM_PROMPT = """
You extract tasks from user input.

Return ONLY valid JSON array.

Example:
Input: "study IELTS 2 hours and go to gym"
Output:
[
  {"task": "IELTS", "duration": 120},
  {"task": "gym", "duration": 60}
]

Rules:
- duration in minutes
- if not specified → 60
- no explanations
- no "json"
- no extra text
"""


def clean_json_response(content):
    content = content.strip()

    if content.startswith("```"):
        parts = content.split("```")
        if len(parts) > 1:
            content = parts[1].strip()

    if content.startswith("json"):
        content = content[4:].strip()

    return content


def parse_tasks(text):
    try:
        response = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text}
            ]
        )
    except Exception as e:
        print("TASK PARSE ERROR:", e)
        return []

    content = response.choices[0].message.content.strip()

    # 🔥 Удаляем ```json или просто json
    content = clean_json_response(content)

    print("CLEANED:", content)

    try:
        return json.loads(content)
    except Exception as e:
        print("JSON ERROR:", e)
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

def parse_fixed_event(text):
    try:
        response = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": """
Detect recurring schedule like school or work.

Return JSON or null.

Format:
{
  "title": "string",
  "start": "HH:MM",
  "end": "HH:MM",
  "days": ["mon","tue"]
}
"""
                },
                {"role": "user", "content": text}
            ]
        )
    except Exception as e:
        print("FIXED EVENT PARSE ERROR:", e)
        return None

    content = clean_json_response(response.choices[0].message.content)

    try:
        return json.loads(content)
    except Exception as e:
        print("FIXED EVENT JSON ERROR:", e)
        return None


@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("Send your tasks")


@dp.message()
async def handle_message(message: types.Message):
    tasks = parse_tasks(message.text)
    event = parse_fixed_event(message.text)

    if not tasks:
        await message.answer("Couldn't understand tasks")
        return

    schedule = build_schedule(tasks)

    result = "🗓 Plan:\n\n"
    for s in schedule:
        result += f"{s['start']} - {s['end']} | {s['task']}\n"

    await message.answer(result)

    if event:
        save_fixed_event(
            message.from_user.id,
            event["title"],
            event["start"],
            event["end"],
            event["days"]
        )

    await message.answer("Saved your schedule")
    return

async def download_voice(bot, voice):
    file = await bot.get_file(voice.file_id)
    file_path = file.file_path

    file_url = f"https://api.telegram.org/file/bot{bot.token}/{file_path}"

    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.get(file_url) as resp:
            data = await resp.read()

    with open("voice.ogg", "wb") as f:
        f.write(data)

    return "voice.ogg"

def speech_to_text(file_path):
    with open(file_path, "rb") as audio_file:
        response = client.audio.transcriptions.create(
            model="deepseek/deepseek-chat:free",
            file=audio_file
        )

    return response.text

@dp.message(lambda message: message.voice)
async def handle_voice(message: types.Message):
    await message.answer("Processing voice...")

    file_path = await download_voice(bot, message.voice)

    try:
        text = speech_to_text(file_path)
        print("TRANSCRIPT:", text)
    except Exception as e:
        await message.answer("Error processing voice")
        print(e)
        return

    tasks = parse_tasks(text)

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
