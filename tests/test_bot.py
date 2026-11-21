import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

def app_module():
    import main
    return main


class ReportFormattingTests(unittest.TestCase):
    def test_markdown_to_telegram_html(self):
        result=app_module().report_to_html("### Главное\n**Важный факт**\n- пункт")
        self.assertIn("<b>Главное</b>",result)
        self.assertIn("<b>Важный факт</b>",result)
        self.assertIn("• пункт",result)
        self.assertNotIn("###",result)
        self.assertNotIn("**",result)

    def test_html_escaping(self):
        result=app_module().report_to_html("**Текст** <script>alert(1)</script> & другое")
        self.assertIn("<b>Текст</b>",result)
        self.assertIn("&lt;script&gt;",result)
        self.assertIn("&amp; другое",result)

    def test_progress_format(self):
        row={"kind":"day","target":"2026-11-21","status":"running",
             "stage":"Обработка", "processed":2,"total":3,"part":1,"parts":2,
             "estimated_usd":0.0012,"error":None}
        result=app_module().analysis_status_text(row)
        self.assertIn("2/3",result)
        self.assertIn("1/2",result)
        self.assertIn("0.0012",result)



class DeletedMessagesTests(unittest.IsolatedAsyncioTestCase):
    async def test_alert_only_on_deletion(self):
        app=app_module()
        app.init_db()
        app.set_deleted_alerts_enabled(True)
        app.save_connection({"id":"deletion-test-connection","user":{"id":100},
                             "is_enabled":True,"rights":{}})
        message={
            "business_connection_id":"deletion-test-connection",
            "chat":{"id":929292,"first_name":"Тестовый собеседник"},
            "message_id":4141,"date":1790000000,
            "from":{"id":929292,"first_name":"Собеседник"},
            "text":"Сообщение, которое потом удалят"
        }
        event={
            "business_connection_id":"deletion-test-connection",
            "chat":{"id":929292,"first_name":"Тестовый собеседник"},
            "message_ids":[4141]
        }
        class UpdateRequest:
            def __init__(self,data):self.data=data
            async def json(self):return self.data
        with patch.object(app,"BOT_OWNER_ID","100"), \
             patch.object(app,"WEBHOOK_SECRET","test-key"), \
             patch.object(app,"send_long_text",new_callable=AsyncMock) as alert:
            await app.webhook(UpdateRequest({"update_id":88001001,"business_message":message}),
                              x_telegram_bot_api_secret_token="test-key")
            alert.assert_not_awaited()
            await app.webhook(UpdateRequest({"update_id":88001002,"deleted_business_messages":event}),
                              x_telegram_bot_api_secret_token="test-key")
            alert.assert_awaited_once()
            text=alert.await_args.args[1]
            self.assertIn("УДАЛЕНО",text)
            self.assertIn("Сообщение, которое потом удалят",text)
            self.assertIn("Собеседник",text)
            self.assertIn("4141",text)
            with app.db() as conn:
                row=conn.execute("SELECT deleted FROM messages WHERE chat_id=? AND message_id=?",
                                 (929292,4141)).fetchone()
            self.assertEqual(row["deleted"],1)
            alert.reset_mock()
            await app.webhook(UpdateRequest({"update_id":88001003,"deleted_business_messages":event}),
                              x_telegram_bot_api_secret_token="test-key")
            alert.assert_not_awaited()

    async def test_unknown_original_explains_limit(self):
        app=app_module()
        app.init_db()
        app.set_deleted_alerts_enabled(True)
        event={"business_connection_id":"deletion-test-connection",
               "chat":{"id":929293,"first_name":"Другой чат"},
               "message_ids":[4888]}
        with patch.object(app,"BOT_OWNER_ID","100"), \
             patch.object(app,"send_long_text",new_callable=AsyncMock) as alert:
            await app.handle_deleted_business_messages(event)
            alert.assert_awaited_once()
            self.assertIn("не получил исходное сообщение",alert.await_args.args[1])

    async def test_disabled_suppresses_notification_but_marks_deleted(self):
        app=app_module()
        app.init_db()
        app.save_connection({"id":"deletion-off-connection","user":{"id":100},
                             "is_enabled":True,"rights":{}})
        app.save_message({
            "business_connection_id":"deletion-off-connection",
            "chat":{"id":929294,"first_name":"Тест"},
            "message_id":4142,"date":1790000000,
            "from":{"id":929294,"first_name":"Собеседник"},"text":"Текст"})
        event={"business_connection_id":"deletion-off-connection",
               "chat":{"id":929294},"message_ids":[4142]}
        with patch.object(app,"BOT_OWNER_ID","100"), \
             patch.object(app,"deleted_alerts_enabled",return_value=False), \
             patch.object(app,"send_long_text",new_callable=AsyncMock) as alert:
            await app.handle_deleted_business_messages(event)
            alert.assert_not_awaited()
        with app.db() as conn:
            row=conn.execute("SELECT deleted FROM messages WHERE chat_id=929294 AND message_id=4142").fetchone()
        self.assertEqual(row["deleted"],1)

class PhotoArchiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_photo_is_saved_and_sent_only_when_message_is_deleted(self):
        app=app_module()
        app.init_db()
        app.set_deleted_alerts_enabled(True)
        event_message={
            "business_connection_id":"photo-test-connection",
            "chat":{"id":935010,"first_name":"Фотосообщения"},
            "message_id":5021,"date":1790000000,
            "from":{"id":935010,"first_name":"Собеседник"},
            "photo":[{"file_id":"telegram-photo-id","file_unique_id":"unique-photo","file_size":5}],
            "caption":"Вот изображение"
        }
        deleted={"business_connection_id":"photo-test-connection",
                 "chat":{"id":935010},"message_ids":[5021]}
        async def fake_download(remote_path,destination):
            destination.parent.mkdir(parents=True,exist_ok=True)
            destination.write_bytes(b"\xff\xd8test\xff\xd9")
            return destination.stat().st_size

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(app,"PHOTO_ARCHIVE_DIR",Path(directory)), \
             patch.object(app,"BOT_OWNER_ID","100"), \
             patch.object(app,"telegram_api",new_callable=AsyncMock) as api, \
             patch.object(app,"download_telegram_photo",new_callable=AsyncMock,side_effect=fake_download) as download, \
             patch.object(app,"send_long_text",new_callable=AsyncMock) as send_text, \
             patch.object(app,"send_archived_photo",new_callable=AsyncMock) as send_photo:
            api.return_value={"file_path":"photos/file_1.jpg","file_size":6}
            app.save_message(event_message)
            self.assertTrue(await app.archive_business_photo(event_message))
            send_text.assert_not_awaited()
            send_photo.assert_not_awaited()
            download.assert_awaited_once()
            with app.db() as con:
                stored=con.execute("""SELECT * FROM archived_photos
                    WHERE connection_id=? AND chat_id=? AND message_id=?""",
                    ("photo-test-connection",935010,5021)).fetchone()
            self.assertIsNotNone(stored)
            self.assertTrue(Path(stored["file_path"]).is_file())
            self.assertEqual(stored["file_size"],len(b"\xff\xd8test\xff\xd9"))
            self.assertTrue(await app.archive_business_photo(event_message))
            download.assert_awaited_once()
            await app.handle_deleted_business_messages(deleted)
            send_text.assert_awaited_once()
            self.assertIn("Вот изображение",send_text.await_args.args[1])
            send_photo.assert_awaited_once()
            self.assertEqual(send_photo.await_args.args[1]["message_id"],5021)
            self.assertTrue(send_photo.await_args.args[2].is_file())
            await app.handle_deleted_business_messages(deleted)
            send_photo.assert_awaited_once()

    async def test_no_photo_archive_if_protected(self):
        app=app_module()
        app.init_db()
        protected={"business_connection_id":"photo-test-connection",
                   "chat":{"id":935010},"message_id":5022,
                   "has_protected_content":True,
                   "photo":[{"file_id":"protected-file-id"}]}
        with patch.object(app,"telegram_api",new_callable=AsyncMock) as api:
            self.assertFalse(await app.archive_business_photo(protected))
            api.assert_not_awaited()

    async def test_missing_photo_retains_text_notification(self):
        app=app_module()
        app.init_db()
        app.set_deleted_alerts_enabled(True)
        event_message={
            "business_connection_id":"photo-missing-connection",
            "chat":{"id":935011,"first_name":"Тест"},
            "message_id":5023,"date":1790000000,
            "from":{"id":935011,"first_name":"Собеседник"},
            "photo":[{"file_id":"unavailable"}]
        }
        app.save_message(event_message)
        event={"business_connection_id":"photo-missing-connection",
               "chat":{"id":935011},"message_ids":[5023]}
        with patch.object(app,"BOT_OWNER_ID","100"), \
             patch.object(app,"send_long_text",new_callable=AsyncMock) as text_alert, \
             patch.object(app,"send_text",new_callable=AsyncMock) as missing_alert:
            await app.handle_deleted_business_messages(event)
            text_alert.assert_awaited_once()
            self.assertIn("[вложение: photo]",text_alert.await_args.args[1])
            missing_alert.assert_awaited_once()
            self.assertIn("не было сохранено",missing_alert.await_args.args[1])


if __name__=="__main__":
    unittest.main()
