import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

_tmp = tempfile.TemporaryDirectory()
os.environ["DATABASE_PATH"] = str(Path(_tmp.name) / "archive.sqlite3")
os.environ["BOT_OWNER_ID"] = "100"
import main


class ArchiveSmokeTest(unittest.TestCase):
    def test_business_messages_and_daily_summary(self):
        main.init_db()
        main.save_connection({
            "id": "connection-test",
            "user": {"id": 100},
            "is_enabled": True,
            "rights": {"can_reply": True},
        })
        now = int(datetime.now(timezone.utc).timestamp())
        main.save_message({
            "business_connection_id": "connection-test",
            "chat": {"id": 200, "title": "Тестовый чат"},
            "message_id": 1,
            "date": now,
            "from": {"id": 100, "first_name": "Alexey"},
            "text": "Мы договорились встретиться завтра",
        })
        main.save_message({
            "business_connection_id": "connection-test",
            "chat": {"id": 200, "title": "Тестовый чат"},
            "message_id": 2,
            "date": now + 1,
            "from": {"id": 300, "first_name": "Собеседник"},
            "text": "Да, подтверждаю встречу",
        })
        rows = main.search_messages("подтверждаю встречу", 10)
        self.assertEqual(len(rows), 1)
        today = datetime.now(main.LOCAL_TZ).date()
        day_rows = main.get_day_messages(today)
        self.assertEqual(len(day_rows), 2)
        self.assertEqual(main.message_author(day_rows[0]), "Алексей")
        self.assertEqual(main.message_author(day_rows[1]), "Собеседник")

        async def fake_call_ai(instructions, input_text, **kwargs):
            return "Подтверждённое резюме тестовой переписки с указанием id сообщений."

        main.call_ai = fake_call_ai
        report = asyncio.run(main.generate_daily_report(today, force=True))
        self.assertIn(today.isoformat(), report)
        saved = main.get_daily_report(today.isoformat())
        self.assertIsNotNone(saved)
        self.assertEqual(saved["message_count"], 2)
        self.assertEqual(saved["chat_count"], 1)

    def test_selected_private_chat_isolated(self):
        main.init_db()
        main.save_connection({
            "id": "connection-contact-test",
            "user": {"id": 100},
            "is_enabled": True,
            "rights": {},
        })
        now = int(datetime.now(timezone.utc).timestamp())
        for chat_id, peer_id, msg_id, body in [
            (7001, 7001, 11, "Сообщение в чате первого собеседника"),
            (7001, 100, 12, "Ответ Алексея в том же чате"),
            (7002, 7002, 21, "Сообщение другого собеседника"),
        ]:
            main.save_message({
                "business_connection_id": "connection-contact-test",
                "chat": {"id": chat_id, "title": f"Чат {chat_id}"},
                "message_id": msg_id,
                "date": now + msg_id,
                "from": {"id": peer_id, "first_name": "Участник"},
                "text": body,
            })
        selected = main.get_contact_messages(7001)
        self.assertEqual(len(selected), 2)
        self.assertEqual({row["chat_id"] for row in selected}, {7001})
        self.assertIn("Ответ Алексея", selected[1]["text"])
        self.assertEqual(main.get_contact_messages(7002)[0]["chat_id"], 7002)
        self.assertIsNone(main.get_contact_report(7001))
        self.assertIn("7001", main.format_archived_chats())


if __name__ == "__main__":
    unittest.main()
