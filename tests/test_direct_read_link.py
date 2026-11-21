"""Owner-only issuance and read-only access via a revocable secret URL.

Do not use a cookie/login or a public anonymous route for the private archive.
"""
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch
from urllib.parse import urlsplit,parse_qs

import httpx
from sync_portal import _hash

# Defer app import until after test_smoke configures test owner/database.
main=None


class DirectReadLinkTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        global main
        if main is None:
            import main as loaded_main
            main=loaded_main
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_patch=patch.object(main,"DATABASE_PATH",Path(tmp.name)/"archive.sqlite3")
        db_patch.start()
        self.addCleanup(db_patch.stop)
        main.init_db()
        main.save_message({
            "business_connection_id":"access-test-connection",
            "chat":{"id":987654321,"title":"Private direct link test"},
            "message_id":42,
            "from":{"id":900,"first_name":"Собеседник"},
            "text":"ПРИВАТНОЕ-СООБЩЕНИЕ-ТЕСТ",
            "date":1795200000,
        })

    async def create_owner_link(self):
        with patch.object(main,"BOT_OWNER_ID","100"), \
             patch.object(main,"send_text",new_callable=AsyncMock) as send:
            await main.private_message({
                "chat":{"id":100,"type":"private"},"from":{"id":100},"text":"/sync_link"})
            response=send.await_args.args[1]
        match=re.search(r"https://\S+/bridge\?access=([A-Za-z0-9_-]+)",response)
        self.assertIsNotNone(match,response)
        return match.group(1)

    def client(self):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                 base_url="https://example.test",follow_redirects=True)

    async def test_anonymous_denied_private_read_and_direct_link_works(self):
        async with self.client() as client:
            for path in ("/bridge/chats","/bridge/chat/987654321","/bridge/search?q=ПРИВАТНОЕ"):
                response=await client.get(path)
                self.assertEqual(response.status_code,401)
                self.assertNotIn("ПРИВАТНОЕ-СООБЩЕНИЕ-ТЕСТ",response.text)
            token=await self.create_owner_link()
            self.assertGreaterEqual(len(token),40)
            with main.db() as db:
                row=db.execute("SELECT token_hash FROM bridge_read_keys").fetchone()
            self.assertEqual(row["token_hash"],_hash(token))
            self.assertNotEqual(row["token_hash"],token)
            root=await client.get("/bridge",params={"access":token})
            self.assertEqual(root.status_code,200)
            self.assertIn("Личный Telegram-архив",root.text)
            self.assertIn("access=",root.text)
            list_resp=await client.get("/bridge/chats",params={"access":token})
            self.assertEqual(list_resp.status_code,200)
            self.assertIn("Private direct link test",list_resp.text)
            self.assertIn("access=",list_resp.text)
            transcript=await client.get("/bridge/chat/987654321",params={"access":token})
            self.assertEqual(transcript.status_code,200)
            self.assertIn("ПРИВАТНОЕ-СООБЩЕНИЕ-ТЕСТ",transcript.text)
            hits=await client.get("/bridge/search",params={"access":token,"q":"ПРИВАТНОЕ"})
            self.assertIn("ПРИВАТНОЕ-СООБЩЕНИЕ-ТЕСТ",hits.text)
            self.assertEqual(hits.status_code,200)
            self.assertIn("access=",hits.text)
            self.assertEqual((await client.get("/bridge/status",params={"access":token})).status_code,200)
            notes=await client.get("/bridge/notes",params={"access":token})
            self.assertEqual(notes.status_code,200)
            self.assertNotIn('action="/bridge/notes" method="post"',notes.text)
            self.assertNotIn('action="/bridge/logout"',notes.text)

    async def test_direct_link_is_readonly_for_note_writes(self):
        token=await self.create_owner_link()
        async with self.client() as client:
            denied=await client.post("/bridge/notes",params={"access":token},
                         data={"csrf":"","subject":"Injected note","content":"NO"})
            self.assertEqual(denied.status_code,401)
        with main.db() as c:
            count=c.execute("SELECT COUNT(*) FROM shared_notes WHERE subject='Injected note'").fetchone()[0]
        self.assertEqual(count,0)

    async def test_rotation_and_revocation(self):
        first=await self.create_owner_link()
        second=await self.create_owner_link()
        self.assertNotEqual(first,second)
        async with self.client() as client:
            self.assertEqual((await client.get("/bridge/chats",params={"access":first})).status_code,401)
            self.assertEqual((await client.get("/bridge/chats",params={"access":second})).status_code,200)
            with patch.object(main,"BOT_OWNER_ID","100"), \
                 patch.object(main,"send_text",new_callable=AsyncMock):
                await main.private_message({
                    "chat":{"id":100,"type":"private"},"from":{"id":100},"text":"/sync_revoke"})
            self.assertEqual((await client.get("/bridge/chats",params={"access":second})).status_code,401)
        with main.db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM bridge_read_keys").fetchone()[0],0)

    async def test_nonowner_cannot_create_or_revoke(self):
        with patch.object(main,"BOT_OWNER_ID","100"), \
             patch.object(main,"send_text",new_callable=AsyncMock) as sent:
            msg={"chat":{"id":101,"type":"private"},"from":{"id":101}}
            await main.private_message({**msg,"text":"/sync_link"})
            self.assertIn("Доступ закрыт",sent.await_args.args[1])
            await main.private_message({**msg,"text":"/sync_revoke"})
        with main.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM bridge_read_keys").fetchone()[0],0)


if __name__=="__main__":
    unittest.main()
