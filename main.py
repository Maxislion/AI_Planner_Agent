import asyncio
import json
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from openai import OpenAI
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
from db import *
from faster_whisper import WhisperModel

whisper_model = WhisperModel("base", compute_type="int8")

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")



client = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url="https://openrouter.ai/api/"
)

router_client = OpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1"
)

# для голоса (OpenAI)
openai_client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

SYSTEM_PROMPT = """
You extract tasks from user input.

Return ONLY valid JSON array.

Example:
Input: "study IELTS 2 hours and go to gym"
Output:
[
  {"task": "IELTS study", "duration": 120},
  {"task": "gym", "duration": 60}
]

Rules:
- duration MUST be in minutes (number)
- convert words to numbers:
  - "one hour" = 60
  - "two hours" = 120
  - "half an hour" = 30
- if duration is missing → use 60
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


def parse_json_content(content, default):
    content = clean_json_response(content)

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        try:
            parsed, _ = json.JSONDecoder().raw_decode(content)
            return parsed
        except json.JSONDecodeError as e:
            print("JSON ERROR:", e)
            return default


def get_today_fixed_events(user_id):
    weekday = datetime.now().strftime("%a").lower()[:3]
    events = get_fixed_events(user_id)
    return [event for event in events if weekday in event.get("days", [])]


def parse_tasks(text):
    try:
        response = router_client.chat.completions.create(
            model="openrouter/auto",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text}
            ]
        )
    except Exception as e:
        print("TASK PARSE ERROR:", e)
        return []

    # 🔥 проверка типа (очень важно)
    if isinstance(response, str):
        print("BAD RESPONSE (string):", response)
        return []

    try:
        content = response.choices[0].message.content.strip()
    except Exception as e:
        print("BAD RESPONSE STRUCTURE:", response)
        print("ERROR:", e)
        return []

    content = clean_json_response(content)

    print("CLEANED:", content)

    return parse_json_content(content, [])


def to_time(t):
    return datetime.strptime(t, "%H:%M")


def to_str(t):
    return t.strftime("%H:%M")


def _old_build_schedule_legacy(tasks, fixed_events):
    current_time = to_time("08:00")
    end_time = to_time("23:00")

    schedule = []

    # 🔥 сначала добавляем fixed events
    for event in fixed_events:
        schedule.append({
            "start": event["start"],
            "end": event["end"],
            "task": event["title"]
        })

    # сортируем по времени
    schedule.sort(key=lambda x: x["start"])

    # 🔥 теперь вставляем задачи после fixed events
    for task in tasks:
        duration = timedelta(minutes=task["duration"])

        # ищем слот после последнего события
        if schedule:
            last_end = to_time(schedule[-1]["end"])
            current_time = last_end

        if current_time + duration > end_time:
            break

        schedule.append({
            "start": to_str(current_time),
            "end": to_str(current_time + duration),
            "task": task["task"]
        })

        current_time += duration + timedelta(minutes=15)

    return schedule


def build_schedule(tasks, fixed_events):
    day_start = to_time("08:00")
    day_end = to_time("23:00")

    schedule = []
    busy_intervals = []

    for event in fixed_events:
        start = to_time(event["start"])
        end = to_time(event["end"])

        if end <= start:
            continue

        if end <= day_start or start >= day_end:
            continue

        if start < day_start:
            start = day_start
        if end > day_end:
            end = day_end

        schedule.append(
            {
                "start": to_str(start),
                "end": to_str(end),
                "task": event["title"],
            }
        )
        busy_intervals.append((start, end))

    busy_intervals.sort(key=lambda interval: interval[0])

    merged_busy = []
    for start, end in busy_intervals:
        if not merged_busy or start > merged_busy[-1][1]:
            merged_busy.append([start, end])
        elif end > merged_busy[-1][1]:
            merged_busy[-1][1] = end

    free_gaps = []
    current = day_start

    for start, end in merged_busy:
        if current < start:
            free_gaps.append([current, start])
        if end > current:
            current = end

    if current < day_end:
        free_gaps.append([current, day_end])

    gap_index = 0

    for task in tasks:
        duration = timedelta(minutes=task["duration"])

        while gap_index < len(free_gaps):
            gap_start, gap_end = free_gaps[gap_index]

            if gap_start + duration <= gap_end:
                task_start = gap_start
                task_end = task_start + duration

                schedule.append(
                    {
                        "start": to_str(task_start),
                        "end": to_str(task_end),
                        "task": task["task"],
                    }
                )

                next_start = task_end + timedelta(minutes=15)
                free_gaps[gap_index][0] = min(next_start, gap_end)

                if free_gaps[gap_index][0] >= gap_end:
                    gap_index += 1
                break

            gap_index += 1

    schedule.sort(key=lambda item: item["start"])
    return schedule


def parse_fixed_event(text):
    if not text:
        return None

    lowered_text = text.lower()
    recurring_markers = [
        "every",
        "daily",
        "weekdays",
        "weekends",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "mon",
        "tue",
        "wed",
        "thu",
        "fri",
        "sat",
        "sun",
    ]

    if not any(marker in lowered_text for marker in recurring_markers):
        return None

    try:
        response = client.chat.completions.create(
            model="openrouter/auto",
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

    content = response.choices[0].message.content.strip()
    event = parse_json_content(content, None)

    if event is None:
        return None

    if not isinstance(event, dict):
        print("FIXED EVENT JSON ERROR: expected object or null")
        return None

    required_fields = ["title", "start", "end", "days"]
    if not all(field in event for field in required_fields):
        return None

    if not isinstance(event["days"], list) or not event["days"]:
        return None

    if not event["title"] or not event["start"] or not event["end"]:
        return None

    return event

def get_emoji(task_name):
    name = task_name.lower().replace("_", " ")

    if "school" in name:
        return "📚"
    if "study" in name or "ielts" in name:
        return "🧠"
    if "gym" in name or "sport" in name:
        return "🏃"
    if "work" in name:
        return "💼"
    return "📌"

def format_task_name(task_name):
    return task_name.replace("_", " ").strip().title()


def build_result_text(schedule):
    lines = ["🗓 Your Plan for Today"]

    for item in schedule:
        emoji = get_emoji(item["task"])
        title = format_task_name(item["task"])
        time_range = f'{item["start"]} – {item["end"]}'

        lines.append("")
        lines.append(f"{emoji} {time_range}")
        lines.append(title)

    return "\n".join(lines)


def build_user_schedule(user_id, tasks):
    fixed_events = get_today_fixed_events(user_id)
    return build_schedule(tasks, fixed_events)


async def process_user_text(message, text):
    print("INPUT TEXT:", text)  # 🔥 debug

    event = parse_fixed_event(text)

    if event:
        save_fixed_event(
            message.from_user.id,
            event["title"],
            event["start"],
            event["end"],
            event["days"]
        )

        await message.answer("✅ Saved your schedule")  # 🔥 убрали план
        return

    tasks = parse_tasks(text)

    # 🔥 fallback если GPT не понял
    if not tasks:
        # 🔥 fallback: попробуем ещё раз с подсказкой
        retry_text = text + " (convert all durations to minutes as numbers)"

        tasks = parse_tasks(retry_text)

        if not tasks:
            await message.answer(f"🤖 I heard:\n{text}")
            await message.answer("❌ Couldn't understand tasks")
            return

    schedule = build_user_schedule(message.from_user.id, tasks)

    await message.answer(build_result_text(schedule))


@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("Send your tasks")


@dp.message(lambda message: message.text is not None)
async def handle_message(message: types.Message):
    await process_user_text(message, message.text)


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
    segments, _ = whisper_model.transcribe(file_path)

    text = ""
    for segment in segments:
        text += segment.text + " "

    return text.strip()

@dp.message(lambda message: message.voice)
async def handle_voice(message: types.Message):
    await message.answer("🎤 Processing voice...")

    file_path = await download_voice(bot, message.voice)

    try:
        text = speech_to_text(file_path)
        print("VOICE TEXT:", text)  # 🔥 debug
    except Exception as e:
        await message.answer("❌ Error processing voice")
        print(e)
        return

    # 🔥 удаляем файл после использования
    import os
    if os.path.exists(file_path):
        os.remove(file_path)

    await process_user_text(message, text)



async def main():
    init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
