import asyncio
import unittest
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

if __name__=="__main__":
    unittest.main()
