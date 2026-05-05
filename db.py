import sqlite3


DB_NAME = "planner.db"


def init_db():
    """Create the database table if it does not already exist."""
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fixed_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT,
                start_time TEXT,
                end_time TEXT,
                days TEXT
            )
            """
        )


def save_fixed_event(user_id, title, start_time, end_time, days):
    """Save one recurring fixed event for a user."""
    init_db()
    days_text = ",".join(days)

    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            """
            DELETE FROM fixed_events
            WHERE user_id = ? AND title = ? AND start_time = ? AND end_time = ?
            """,
            (user_id, title, start_time, end_time),
        )
        conn.execute(
            """
            INSERT INTO fixed_events (user_id, title, start_time, end_time, days)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, title, start_time, end_time, days_text),
        )


def get_fixed_events(user_id):
    """Return all fixed events for a user as a list of dictionaries."""
    init_db()

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute(
            """
            SELECT title, start_time, end_time, days
            FROM fixed_events
            WHERE user_id = ?
            ORDER BY id
            """,
            (user_id,),
        )
        rows = cursor.fetchall()

    events = []
    for title, start_time, end_time, days_text in rows:
        events.append(
            {
                "title": title,
                "start": start_time,
                "end": end_time,
                "days": days_text.split(",") if days_text else [],
            }
        )

    return events


def delete_all_events(user_id):
    """Delete all fixed events for a user."""
    init_db()

    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            "DELETE FROM fixed_events WHERE user_id = ?",
            (user_id,),
        )


if __name__ == "__main__":
    test_user_id = 12345

    init_db()
    delete_all_events(test_user_id)

    save_fixed_event(
        user_id=test_user_id,
        title="School",
        start_time="08:00",
        end_time="14:00",
        days=["mon", "tue", "wed", "thu", "fri"],
    )
    save_fixed_event(
        user_id=test_user_id,
        title="Gym",
        start_time="18:00",
        end_time="19:00",
        days=["mon", "wed", "fri"],
    )

    print("Saved events:")
    print(get_fixed_events(test_user_id))

    delete_all_events(test_user_id)
    print("After delete:")
    print(get_fixed_events(test_user_id))
