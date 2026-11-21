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



class ExpiringMediaTests(unittest.TestCase):
    def test_view_once_flag_detection(self):
        app=app_module()
        photo=[{"file_id":"photo-id"}]
        self.assertTrue(app.is_expiring_photo({"photo":photo,"ttl_seconds":2147483647}))
        self.assertTrue(app.is_expiring_photo({"photo":photo,"view_once":True}))
        self.assertFalse(app.is_expiring_photo({"photo":photo}))
        self.assertFalse(app.is_expiring_photo({"ttl_seconds":10}))

    def test_owner_can_save_photo_from_reply(self):
        app=app_module()
        message={
            "chat":{"id":222,"first_name":"Собеседник"},
            "from":{"id":100},
            "text":"/save_once",
            "reply_to_message":{
                "message_id":9,
                "from":{"id":222,"first_name":"Собеседник"},
                "photo":[{"file_id":"file-test","file_size":123}]
            }
        }
        with patch.object(app,"BOT_OWNER_ID","100"), \
             patch.object(app,"mirror_enabled",return_value=True), \
             patch.object(app,"copy_photo_to_owner",new_callable=AsyncMock,return_value=True) as copy:
            asyncio.run(app.maybe_copy_replied_photo(message))
        copy.assert_awaited_once()
        self.assertEqual(copy.await_args.args[0],"file-test")
        self.assertEqual(copy.await_args.args[2],100)

    def test_unrequested_plain_reply_does_not_capture(self):
        app=app_module()
        message={
            "chat":{"id":222},"from":{"id":100},"text":"Окей",
            "reply_to_message":{"photo":[{"file_id":"file-test"}],"from":{"id":222}}
        }
        with patch.object(app,"BOT_OWNER_ID","100"), \
             patch.object(app,"mirror_enabled",return_value=True), \
             patch.object(app,"copy_photo_to_owner",new_callable=AsyncMock) as copy:
            asyncio.run(app.maybe_copy_replied_photo(message))
        copy.assert_not_awaited()

    def test_protected_reply_not_copied(self):
        app=app_module()
        message={
            "from":{"id":100},"text":"/save_once",
            "reply_to_message":{"photo":[{"file_id":"secret"}],"has_protected_content":True}
        }
        with patch.object(app,"BOT_OWNER_ID","100"), \
             patch.object(app,"mirror_enabled",return_value=True), \
             patch.object(app,"copy_photo_to_owner",new_callable=AsyncMock) as copy, \
             patch.object(app,"send_text",new_callable=AsyncMock):
            asyncio.run(app.maybe_copy_replied_photo(message))
        copy.assert_not_awaited()

if __name__=="__main__":
    unittest.main()
