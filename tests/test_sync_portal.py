"""End-to-end private browser bridge checks: owner pairing, sessions and notes."""
import tempfile
import unittest
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import main
from sync_portal import create_login_code, redeem_login_code, create_read_link, revoke_read_link, _hash


class PortalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_patch=patch.object(main,"DATABASE_PATH",Path(self.temp.name)/"archive.sqlite3")
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        main.init_db()
        main.save_message({
            "business_connection_id":"portal-connection",
            "chat":{"id":577701,"first_name":"Личный тест"},
            "message_id":1001,
            "from":{"id":577701,"first_name":"Иван"},
            "text":"Секретная фраза",
            "date":1780000000
        })

    async def test_guest_cannot_read_and_owner_can_log_in(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app),
            base_url="https://testserver",follow_redirects=True
        ) as client:
            guest=await client.get("/bridge/chat/577701")
            self.assertEqual(guest.status_code,401)
            self.assertNotIn("Секретная фраза",guest.text)
            landing=await client.get("/bridge")
            self.assertIn("/sync_link",landing.text)
            self.assertNotIn("Секретная фраза",landing.text)
            self.assertIn("no-store",landing.headers["Cache-Control"])
            secret=create_login_code(main.db)
            invalid=await client.post("/bridge/login",data={"code":"totally-wrong"})
            self.assertIn("Неверный",invalid.text)
            valid=await client.post("/bridge/login",data={"code":secret})
            self.assertEqual(valid.status_code,200)
            self.assertIn("Личный Telegram-архив",valid.text)
            self.assertIn("alexey_bridge_session",client.cookies)
            chats=await client.get("/bridge/chats")
            self.assertIn("Личный тест",chats.text)
            messages=await client.get("/bridge/chat/577701")
            self.assertIn("Секретная фраза",messages.text)
            self.assertIn("Секретная фраза",(await client.get("/bridge/search?q=Секретная")).text)
            notes=await client.get("/bridge/notes")
            self.assertIn("Общие заметки",notes.text)
            self.assertNotIn("Секретная фраза",notes.text)
            import re
            import html
            csrf=html.unescape(re.search(r'name="csrf" type="hidden" value="([^"]+)"',notes.text).group(1))
            denied=await client.post("/bridge/notes",data={"csrf":"incorrect","subject":"Test","content":"Value"})
            self.assertEqual(denied.status_code,403)
            written=await client.post("/bridge/notes",data={
                "csrf":csrf,"subject":"Связь с ChatGPT","content":"Общая заметка"
            })
            self.assertEqual(written.status_code,200)
            self.assertIn("Общая заметка",written.text)
            self.assertIn("Общая заметка",main.sync_notes_text())
            with main.db() as c:
                last=c.execute("SELECT source FROM shared_notes ORDER BY id DESC LIMIT 1").fetchone()
                self.assertEqual(last["source"],"chatgpt")
            assert (await client.get("/bridge/status")).status_code==200
            logout=await client.post("/bridge/logout")
            self.assertIn("/sync_link",logout.text)
            self.assertEqual((await client.get("/bridge/chat/577701")).status_code,401)

    async def test_expired_and_reused_codes(self):
        code=create_login_code(main.db)
        self.assertEqual(len(code)>=30,True)
        with main.db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM bridge_sessions").fetchone()[0],0)
        first=redeem_login_code(main.db,code)
        self.assertTrue(first)
        self.assertIsNone(redeem_login_code(main.db,code))
        code2=create_login_code(main.db)
        with main.db() as c:
            c.execute("UPDATE bridge_login_codes SET expires_at=1")
        self.assertIsNone(redeem_login_code(main.db,code2))
        self.assertNotEqual(code,code2)
        with main.db() as c:
            row=c.execute("SELECT session_hash FROM bridge_sessions").fetchone()
            self.assertNotEqual(row["session_hash"],first)
            self.assertEqual(row["session_hash"],_hash(first))

    async def test_direct_read_only_link_without_cookies(self):
        from urllib.parse import urlparse,parse_qs
        url=create_read_link(main.db,"https://testserver")
        token=parse_qs(urlparse(url).query)["access"][0]
        self.assertGreaterEqual(len(token),40)
        # Server persists only a hash - never the secret itself.
        with main.db() as c:
            saved=c.execute("SELECT token_hash FROM bridge_read_keys WHERE key_id=1").fetchone()
            self.assertEqual(saved["token_hash"],_hash(token))
            self.assertNotEqual(saved["token_hash"],token)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app),
            base_url="https://testserver",follow_redirects=True
        ) as client:
            self.assertEqual((await client.get("/bridge/chats")).status_code,401)
            root=await client.get(url)
            self.assertEqual(root.status_code,200)
            self.assertIn("Личный Telegram-архив",root.text)
            # The navigation carries access to deeper pages, without a cookie.
            from html import unescape
            import re
            match=re.search(r'href="([^"]*?/bridge/chats[^"]*)"',root.text)
            self.assertIsNotNone(match)
            chat_url=unescape(match.group(1))
            self.assertIn("access=",chat_url)
            listing=await client.get(chat_url)
            self.assertEqual(listing.status_code,200)
            self.assertIn("Личный тест",listing.text)
            match=re.search(r'href="([^"]*?/bridge/chat/577701[^"]*)"',listing.text)
            self.assertIsNotNone(match)
            message_url=unescape(match.group(1))
            messages=await client.get(message_url)
            self.assertIn("Секретная фраза",messages.text)
            self.assertNotIn("csrf",messages.text)
            self.assertNotIn("Выйти",root.text)
            self.assertIn("Секретная фраза",
                         (await client.get("/bridge/search",params={
                             "access":token,"q":"Секретная"})).text)
            notes=await client.get("/bridge/notes",params={"access":token})
            self.assertEqual(notes.status_code,200)
            self.assertNotIn('method="post"',notes.text)
            self.assertEqual((await client.post("/bridge/notes",params={"access":token},
                data={"csrf":"","subject":"X","content":"No"})).status_code,401)
            self.assertEqual((await client.get("/bridge/chats",params={
                "access":"invalid"})).status_code,401)
            self.assertNotIn("Секретная фраза",
                             (await client.get("/bridge/chats")).text)
        revoke_read_link(main.db)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
            base_url="https://testserver") as client:
            self.assertEqual((await client.get(url)).status_code,200)
            self.assertIn("/sync_link",(await client.get(url)).text)
            self.assertEqual((await client.get("/bridge/chats",params={
                "access":token})).status_code,401)

    async def test_rotating_link_revokes_older_link(self):
        from urllib.parse import urlparse,parse_qs
        previous=create_read_link(main.db,"https://testserver")
        current=create_read_link(main.db,"https://testserver")
        self.assertNotEqual(previous,current)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
            base_url="https://testserver") as client:
            self.assertEqual((await client.get("/bridge/chats",params={
                "access":parse_qs(urlparse(previous).query)["access"][0]})).status_code,401)
            self.assertEqual((await client.get("/bridge/chats",params={
                "access":parse_qs(urlparse(current).query)["access"][0]})).status_code,200)

    async def test_only_telegram_owner_can_issue_access_link(self):
        with patch.object(main,"BOT_OWNER_ID","100"), \
             patch.object(main,"send_text",new_callable=AsyncMock) as send:
            await main.private_message({"chat":{"type":"private","id":887},
                                        "from":{"id":887},"text":"/sync_link"})
            self.assertIn("Доступ закрыт",send.await_args.args[1])
            with main.db() as c:
                self.assertEqual(c.execute("SELECT COUNT(*) FROM bridge_read_keys").fetchone()[0],0)
            await main.private_message({"chat":{"type":"private","id":100},
                                        "from":{"id":100},"text":"/sync_link"})
            self.assertIn("Прямой доступ",send.await_args.args[1])
            self.assertIn("/bridge?access=",send.await_args.args[1])
            with main.db() as c:
                self.assertEqual(c.execute("SELECT COUNT(*) FROM bridge_read_keys").fetchone()[0],1)
            await main.private_message({"chat":{"type":"private","id":100},
                                        "from":{"id":100},"text":"/sync_revoke"})
            self.assertIn("отключена",send.await_args.args[1])
            with main.db() as c:
                self.assertEqual(c.execute("SELECT COUNT(*) FROM bridge_read_keys").fetchone()[0],0)


if __name__=="__main__":
    unittest.main()
