"""Regression coverage for the privacy-preserving owner diagnostics center."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


def app_module():
    import main
    return main


class DiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.app=app_module()
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_patch=patch.object(self.app,"DATABASE_PATH",Path(self.tmp.name)/"archive.sqlite3")
        self.photo_patch=patch.object(self.app,"PHOTO_ARCHIVE_DIR",Path(self.tmp.name)/"photos")
        self.db_patch.start()
        self.photo_patch.start()
        self.addCleanup(self.photo_patch.stop)
        self.addCleanup(self.db_patch.stop)
        self.app.init_db()

    def test_connection_archive_and_activity_distinction(self):
        app=self.app
        app.save_connection({"id":"diagnostics-c1","user":{"id":100},
                             "is_enabled":True,"rights":{}})
        app.save_message({
            "business_connection_id":"diagnostics-c1",
            "chat":{"id":941101,"first_name":"Собеседник"},
            "message_id":501,"date":1750000000,
            "from":{"id":941101,"first_name":"Private Person"},
            "text":"Секретное содержимое переписки"
        })
        app.diagnostic_activity("diagnostics-c1",941101,"new")
        data=app.diagnostics_snapshot()
        self.assertEqual(data["business"]["active"],1)
        self.assertEqual(data["messages"]["total"],1)
        self.assertEqual(data["activity"]["new"],data["active_chats"][0]["last_at"])
        report=app.diagnostics_text(data,webhook={"url":"https://example.test/telegram/webhook",
                                                  "pending_update_count":3})
        self.assertIn("Подключений: 1 активных из 1",report)
        self.assertIn("Telegram pending updates: 3",report)
        self.assertIn("Чатов в архиве: 1",report)
        self.assertIn("Последнее новое сообщение (получено ботом)",report)
        self.assertNotIn("Секретное содержимое",report)
        self.assertNotIn("Private Person",report)

    async def test_webhook_check_and_fallback(self):
        app=self.app
        with patch.object(app,"WEBHOOK_URL","https://example.test"), \
             patch.object(app,"BOT_TOKEN","placeholder"), \
             patch.object(app,"MT_PROTO_ENABLED",False), \
             patch.object(app,"telegram_api",new_callable=AsyncMock,
                          return_value={"url":"https://example.test/telegram/webhook",
                                        "pending_update_count":0}) as api:
            result=await app.diagnostics_report()
            self.assertIn("✅ адрес совпадает",result)
            api.assert_awaited_once_with("getWebhookInfo",{})
        with patch.object(app,"WEBHOOK_URL","https://example.test"), \
             patch.object(app,"BOT_TOKEN","placeholder"), \
             patch.object(app,"telegram_api",new_callable=AsyncMock,
                          side_effect=RuntimeError("token must not be leaked")):
            result=await app.diagnostics_report()
            self.assertIn("не удалось проверить",result)
            self.assertNotIn("token must not be leaked",result)
        data=app.diagnostics_snapshot()
        self.assertEqual(data["error_count"],1)
        self.assertEqual(data["errors"][0]["code"],"webhook_check_failed")

    def test_photo_health_and_safe_errors(self):
        app=self.app
        photo=app.PHOTO_ARCHIVE_DIR/"saved.jpg"
        photo.parent.mkdir(parents=True,exist_ok=True)
        photo.write_bytes(b"example")
        missing=app.PHOTO_ARCHIVE_DIR/"absent.jpg"
        with app.db() as c:
            for mid,path in ((1,photo),(2,missing)):
                c.execute("""INSERT INTO archived_photos(
                    connection_id,chat_id,message_id,photo_unique_id,file_path,file_size,saved_at)
                    VALUES(?,?,?,?,?,?,?)""",
                    ("diag-c2",941102,mid,f"unique{mid}",str(path),7,mid))
        app.diagnostic_event("photos","download_failed",941102)
        app.diagnostic_event("photos","not a valid code",941102)
        snap=app.diagnostics_snapshot()
        self.assertEqual(snap["photos"]["total"],2)
        self.assertEqual(snap["photo_sample_count"],2)
        self.assertEqual(snap["photo_sample_missing"],1)
        self.assertEqual(snap["error_count"],1)
        report=app.diagnostics_text(snap,webhook_error=True)
        self.assertIn("Проверка файлов: 1/2",report)
        self.assertIn("download_failed",report)
        self.assertIn("не удалось проверить",report)

    def test_chat_breakdown_and_empty(self):
        app=self.app
        self.assertIn("данных пока нет",app.diagnostics_chat_text(941106))
        app.save_message({
            "business_connection_id":"diag-c3",
            "chat":{"id":941106,"first_name":"Тест"},
            "message_id":17,"date":1790000000,
            "from":{"id":941106,"first_name":"Тест"},
            "text":"Текст"})
        app.diagnostic_activity("diag-c3",941106,"edit")
        report=app.diagnostics_chat_text(941106)
        self.assertIn("В архиве сообщений: 1",report)
        self.assertIn("изменение",report)
        self.assertIn("/edits 941106",report)
        self.assertNotIn("Текст",report)

    async def test_diagnostics_owner_only_and_help(self):
        app=self.app
        with patch.object(app,"BOT_OWNER_ID","100"), \
             patch.object(app,"BOT_TOKEN","placeholder"), \
             patch.object(app,"WEBHOOK_URL","https://example.test"), \
             patch.object(app,"telegram_api",new_callable=AsyncMock,
                          return_value={"url":"https://example.test/telegram/webhook",
                                        "pending_update_count":0}), \
             patch.object(app,"send_long_text",new_callable=AsyncMock) as long_send, \
             patch.object(app,"send_text",new_callable=AsyncMock) as short_send:
            await app.private_message({"chat":{"id":999,"type":"private"},
                                       "from":{"id":999},"text":"/diagnostics"})
            short_send.assert_awaited_once()
            self.assertIn("Доступ закрыт",short_send.await_args.args[1])
            long_send.assert_not_awaited()
            short_send.reset_mock()
            await app.private_message({"chat":{"id":100,"type":"private"},
                                       "from":{"id":100},"text":"/diagnostics"})
            long_send.assert_awaited_once()
            self.assertIn("ДИАГНОСТИКА ALEXEY AI",long_send.await_args.args[1])
            long_send.reset_mock()
            await app.private_message({"chat":{"id":100,"type":"private"},
                                       "from":{"id":100},"text":"/diagnostics_chat 941106"})
            long_send.assert_awaited_once()
            self.assertIn("данных пока нет",long_send.await_args.args[1])
            long_send.reset_mock()
            await app.private_message({"chat":{"id":100,"type":"private"},
                                       "from":{"id":100},"text":"/help"})
            self.assertIn("/diagnostics_chat ID",short_send.await_args.args[1])


if __name__=="__main__":
    unittest.main()
