from pathlib import Path
import sqlite3

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / 'accelx.db'


def record_event(metric: str, title: str, detail: str, user_email: str = '') -> None:
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute('INSERT INTO user_metrics(user_email, key, value) VALUES (?, ?, 1) ON CONFLICT(user_email, key) DO UPDATE SET value = value + 1', (user_email, metric))
        connection.execute('INSERT INTO activity(user_email, title, detail) VALUES (?, ?, ?)', (user_email, title, detail))


def dashboard_snapshot(user_email: str, days: int | str = 30) -> tuple[dict, list[dict], list[dict]]:
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        metrics = {row['key']: row['value'] for row in connection.execute('SELECT key,value FROM user_metrics WHERE user_email = ?', (user_email,))}
        if days == 'current':
            activities = [dict(row) for row in connection.execute("SELECT title,detail,created_at FROM activity WHERE user_email = ? AND date(created_at) = date('now') ORDER BY id DESC LIMIT 5", (user_email,))]
            throughput_rows = connection.execute('''
                WITH modules(label, event_title, sort_order) AS (
                    VALUES ('Mapping Validator', 'Mapping workbook validated', 1),
                           ('SQL Generator', 'SQL artifact generated', 2),
                           ('Prod Parity', 'Parity check passed', 3),
                           ('Test Data Forge', 'Synthetic sample exported', 4)
                )
                SELECT modules.label, COUNT(activity.id) AS total
                FROM modules
                LEFT JOIN activity ON activity.title = modules.event_title
                    AND activity.user_email = ?
                    AND date(activity.created_at) = date('now')
                GROUP BY modules.label, modules.sort_order
                ORDER BY modules.sort_order
            ''', (user_email,))
            return metrics, activities, [dict(row) for row in throughput_rows]
        activities = [dict(row) for row in connection.execute('SELECT title,detail,created_at FROM activity WHERE user_email = ? AND created_at >= datetime(\'now\', ?) ORDER BY id DESC LIMIT 5', (user_email, f'-{days} days'))]
        throughput_rows = connection.execute('''
            WITH RECURSIVE dates(day) AS (
                SELECT date('now', ?)
                UNION ALL
                SELECT date(day, '+1 day') FROM dates WHERE day < date('now')
            )
            SELECT dates.day, COUNT(activity.id) AS total
            FROM dates
            LEFT JOIN activity ON activity.user_email = ? AND date(activity.created_at) = dates.day
            GROUP BY dates.day
            ORDER BY dates.day
        ''', (f'-{days - 1} days', user_email))
        throughput = [dict(row) for row in throughput_rows]
    return metrics, activities, throughput
