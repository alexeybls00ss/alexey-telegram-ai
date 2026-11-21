"""Safe explicit export and shared-note bridge between Telegram and ChatGPT."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import main


class SyncBridgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_patch=patch.object(main,"DATABASE_PATH",Path(self.temp.name)/"archive.sqlite3")
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        main.init_db()
        for chat_id,msg_id,text in [
            (552210,1,"Привет"),
            (552210,2,"Увидимся завтра"),
            (552210,3,"Позже"),
            (552211,4,"Текст другого чата")
        ]:
            main.save_message({
                "business_connection_id":"sync-conn",
                "chat":{"id":chat_id,"first_name":f"Чат {chat_id}"},
                "message_id":msg_id,"date":1790000000+msg_id,
                "from":{"id":chat_id,"first_name":"Тест"},
                "text":text
            })

    def test_selected_chat_only_and_sorted(self):
        data=main.sync_export_payload(552210,2)
        self.assertEqual(data["format"],"alexey-ai-chat-export-v1")
        self.assertEqual(data["chat_id"],552210)
        self.assertEqual(data["count"],2)
        self.assertFalse(data["includes_media_files"])
        self.assertEqual([x["message_id"] for x in data["messages"]],[2,3])
        self.assertNotIn("Текст другого чата",json.dumps(data,ensure_ascii=False))
        for args in [(552210,0),(552210,201),(552211,300)]:
            with self.assertRaises(ValueError):main.sync_export_payload(*args)
        with self.assertRaises(ValueError):main.sync_export_payload(552299)
        self.assertIn("Увидимся",json.dumps(data,ensure_ascii=False))

    def test_note_validation_and_status(self):
        note_id=main.add_shared_note("Событие","Запомни важную дату")
        self.assertGreater(note_id,0)
        self.assertIn("Событие",main.sync_notes_text())
        with self.assertRaises(ValueError):main.add_shared_note("", "text")
        with self.assertRaises(ValueError):main.add_shared_note("Valid", " ")
        with self.assertRaises(ValueError):main.add_shared_note("Title","Text",source="invalid")
        self.assertIn("Общие заметки: 1",main.sync_status_text())

    async def test_only_owner_can_export_or_add_notes(self):
        with patch.object(main,"BOT_OWNER_ID","100"), \
             patch.object(main,"send_sync_export",new_callable=AsyncMock) as deliver, \
             patch.object(main,"send_text",new_callable=AsyncMock) as respond:
            await main.private_message({"chat":{"type":"private","id":888},
                                        "from":{"id":888},"text":"/sync_export 552210"})
            deliver.assert_not_awaited()
            self.assertIn("Доступ закрыт",respond.await_args.args[1])
            await main.private_message({"chat":{"type":"private","id":888},
                                        "from":{"id":888},"text":"/sync_note Тема | Секрет"})
            with main.db() as c:
                self.assertEqual(c.execute("SELECT COUNT(*) FROM shared_notes").fetchone()[0],0)
            await main.private_message({"chat":{"type":"private","id":100},
                                        "from":{"id":100},"text":"/sync_export 552210 3"})
            deliver.assert_awaited_once_with(100,552210,3)
            await main.private_message({"chat":{"type":"private","id":100},
                                        "from":{"id":100},"text":"/sync_note Мои планы | Посмотреть Москву"})
            self.assertIn("сохранена",respond.await_args.args[1])
            with main.db() as c:
                row=c.execute("SELECT subject,content,source FROM shared_notes").fetchone()
                self.assertEqual(tuple(row),("Мои планы","Посмотреть Москву","telegram"))

    async def test_protected_api_reads_and_writes_notes(self):
        secret="x"*50
        main.app.router  # confirm router is available
        transport=httpx.ASGITransport(app=main.app)
        with patch.object(main,"INTEGRATION_TOKEN",secret):
            async with httpx.AsyncClient(transport=transport,base_url="http://test") as client:
                unauth=await client.get("/integration/chats")
                self.assertEqual(unauth.status_code,401)
                authenticated=await client.get("/integration/chats",
                    headers={"Authorization":"Bearer "+secret})
                self.assertEqual(authenticated.status_code,200)
                self.assertGreater(len(authenticated.json()["chats"]),0)
                invalid=await client.post("/integration/notes",json={
                    "subject":"Мой факт","content":"Новая заметка"})
                self.assertEqual(invalid.status_code,401)
                good=await client.post("/integration/notes",json={
                    "subject":"Мой факт","content":"Новая заметка"},
                    headers={"Authorization":"Bearer "+secret})
                self.assertEqual(good.status_code,200)
                notes=await client.get("/integration/notes",
                    headers={"Authorization":"Bearer "+secret})
                self.assertEqual(notes.status_code,200)
                self.assertEqual(notes.json()["notes"][0]["subject"],"Мой факт")
        with patch.object(main,"INTEGRATION_TOKEN",""):
            async with httpx.AsyncClient(transport=transport,base_url="http://test") as client:
                self.assertEqual((await client.get("/integration/chats")).status_code,503)

    async def test_export_is_json_document_only_for_owner(self):
        payload=main.sync_export_payload(552210,1)
        fake_response=httpx.Response(200,json={"ok":True},request=httpx.Request("POST","https://api.telegram.org"))
        calls=[]
        def handler(request):
            calls.append(request)
            return fake_response
        transport=httpx.MockTransport(handler)
        real_cls=httpx.AsyncClient
        def make_client(*args,**kwargs):
            kwargs["transport"]=transport
            return real_cls(*args,**kwargs)
        with patch.object(main,"BOT_TOKEN","test-placeholder"), \
             patch.object(main.httpx,"AsyncClient",side_effect=make_client):
            count=await main.send_sync_export(100,552210,1)
        self.assertEqual(count,payload["count"])
        self.assertEqual(len(calls),1)
        self.assertIn("sendDocument",str(calls[0].url))
        self.assertIn(b"alexey-ai-chat-export-v1",calls[0].content)
        self.assertNotIn(b"Текст другого чата",calls[0].content)


if __name__=="__main__":
    unittest.main()
