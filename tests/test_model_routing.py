"""Regression tests: smart OpenAI routing, protected premium, token-cost accounting."""
import asyncio
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import AsyncMock,patch

import httpx
import main
from model_routing import (
    MINI,NANO,PREMIUM,route_question,token_cost_usd,projected_cost_usd,
    model_for_tier
)


class SmartModelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patch_db=patch.object(main,"DATABASE_PATH",Path(self.tmp.name)/"archive.sqlite3")
        self.patch_db.start()
        self.addCleanup(self.patch_db.stop)
        main.PENDING_ANALYSES.clear()
        self.addCleanup(main.PENDING_ANALYSES.clear)
        main.init_db()

    def test_simple_vs_analysis_and_never_automatic_premium(self):
        self.assertEqual(route_question("Когда мы говорили о подарке?"),"simple")
        self.assertEqual(route_question("Найди сообщение о встрече"),"simple")
        self.assertEqual(route_question("Привет"),"simple")
        self.assertEqual(route_question("Проанализируй историю общения"),"analysis")
        self.assertEqual(route_question("Почему изменились отношения?"),"analysis")
        self.assertEqual(route_question("Сравни 2025 и 2026"),"analysis")
        self.assertEqual(route_question("Напиши большой доклад"),"analysis")
        self.assertEqual(route_question("Найди и подробно проанализируй обещания"),"analysis")
        self.assertEqual(route_question("Найди всё о "+("друг"*90)),"analysis")
        for q in ("Кто был первым?", "Анализируй всю историю", "Включи самую дорогую модель"):
            self.assertNotEqual(route_question(q),"premium")
        self.assertEqual(model_for_tier("simple"),NANO)
        self.assertEqual(model_for_tier("analysis"),MINI)
        self.assertEqual(model_for_tier("premium"),PREMIUM)
        with self.assertRaises(ValueError):model_for_tier("unknown")

    def test_pricing_cache_and_estimates(self):
        # 900 input tokens, of which 200 cached; 120 generated tokens.
        self.assertAlmostEqual(token_cost_usd(NANO,900,120,200),0.000294)
        self.assertAlmostEqual(token_cost_usd(MINI,900,120,200),
                               (700*0.75+200*0.075+120*4.5)/1_000_000)
        self.assertAlmostEqual(token_cost_usd(PREMIUM,1000000,100000,0),4)
        # Malformed cache counts cannot create a negative cost.
        self.assertAlmostEqual(token_cost_usd(NANO,200,5,999999),
                               (200*0.02+5*1.25)/1_000_000)
        self.assertGreater(projected_cost_usd(PREMIUM,2000,2000),
                           projected_cost_usd(NANO,2000,2000))
        with self.assertRaises(ValueError):token_cost_usd("nonexistent",12,1)

    async def test_api_uses_right_model_and_persists_cost(self):
        captured=[]
        def responder(request):
            body=json.loads(request.content)
            captured.append(body)
            return httpx.Response(200,json={
                "model":body["model"],
                "output":[{"type":"message","content":[{"type":"output_text","text":"Нашёл дату."}]}],
                "usage":{"input_tokens":900,"output_tokens":120,
                         "input_tokens_details":{"cached_tokens":200}}
            })
        transport=httpx.MockTransport(responder)
        actual_client=httpx.AsyncClient
        def make_client(*args,**kwargs):
            kwargs["transport"]=transport
            return actual_client(*args,**kwargs)
        with patch.object(main,"OPENAI_API_KEY","redacted-test"), \
             patch.object(main.httpx,"AsyncClient",side_effect=make_client):
            result=await main.call_ai("Бот","Когда встреча?",max_output_tokens=120,tier="simple")
            self.assertIn("Нашёл",result)
            await main.call_ai("Бот","Анализ",max_output_tokens=120,tier="analysis")
            with self.assertRaises(PermissionError):
                await main.call_ai("Бот","сложное",tier="premium")
            auth=main.PREMIUM_AUTHORIZED.set(True)
            try:
                await main.call_ai("Бот","сложное",max_output_tokens=120,tier="premium")
            finally:
                main.PREMIUM_AUTHORIZED.reset(auth)
        self.assertEqual([x["model"] for x in captured],[NANO,MINI,PREMIUM])
        with main.db() as c:
            rows=c.execute("""SELECT model,tier,input_tokens,output_tokens,cached_input_tokens,
                                     estimated_cost_usd FROM api_usage ORDER BY id""").fetchall()
        self.assertEqual([r["tier"] for r in rows],["simple","analysis","premium"])
        self.assertEqual(rows[0]["cached_input_tokens"],200)
        self.assertAlmostEqual(rows[0]["estimated_cost_usd"],0.000294)

    async def test_estimated_budget_blocks_unapproved_cost(self):
        with patch.object(main,"OPENAI_API_KEY","test"):
            token=main.ACTIVE_ANALYSIS_BUDGET.set({"limit":0.000001,"spent":0.0})
            try:
                with self.assertRaises(main.AnalysisBudgetExceeded):
                    await main.call_ai("test","expensive",max_output_tokens=2000,tier="analysis")
            finally:
                main.ACTIVE_ANALYSIS_BUDGET.reset(token)

    def test_unpriced_legacy_rows_not_falsely_billed(self):
        with main.db() as c:
            c.execute("""INSERT INTO api_usage(created_at,model,input_tokens,output_tokens)
                         VALUES(?,?,?,?)""",
                      (int(datetime.now(timezone.utc).timestamp()),"gpt-5.4-mini",1200,900))
        result=main.archive_usage()
        self.assertIn("Старые запросы без записанной стоимости: 1",result)
        self.assertIn("0.0000 USD",result)
        self.assertIn("не фактическое списание",result)
        self.assertIn("gpt-5.4-mini",result)

    def test_migrate_existing_usage_table_without_data_loss(self):
        # The old table is restored before starting init_db, then upgraded.
        with main.db() as c:
            c.execute("DROP TABLE api_usage")
            c.execute("""CREATE TABLE api_usage(id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at INTEGER,model TEXT,input_tokens INTEGER,output_tokens INTEGER)""")
            c.execute("""INSERT INTO api_usage(created_at,model,input_tokens,output_tokens)
                VALUES(?,?,?,?)""",(10,"old-model",100,20))
        main.init_db()
        with main.db() as c:
            cols={x["name"] for x in c.execute("PRAGMA table_info(api_usage)")}
            row=c.execute("SELECT * FROM api_usage WHERE model='old-model'").fetchone()
        self.assertTrue({"tier","cached_input_tokens","estimated_cost_usd"}.issubset(cols))
        self.assertEqual(row["input_tokens"],100)
        self.assertIsNone(row["estimated_cost_usd"])

    async def test_premium_requires_explicit_owner_confirm(self):
        async def fake_answer(question,tier=None):
            self.assertEqual(tier,"premium")
            self.assertTrue(main.PREMIUM_AUTHORIZED.get())
            self.assertEqual(question,"Подробно проанализируй изменения общения с Иваном")
            return "Разбор готов"
        tasks=[]
        with patch.object(main,"BOT_OWNER_ID","100"), \
             patch.object(main,"ask_ai",side_effect=fake_answer), \
             patch.object(main,"send_text",new_callable=AsyncMock) as sent, \
             patch.object(main,"send_long_text",new_callable=AsyncMock) as long_sent, \
             patch.object(main.asyncio,"create_task",side_effect=lambda coro: tasks.append(coro)):
            # A stranger cannot ask to use premium.
            await main.private_message({"chat":{"id":999,"type":"private"},
                "from":{"id":999},"text":"/deep Подробно проанализируй изменения общения с Иваном"})
            self.assertEqual(main.PENDING_ANALYSES,{})
            msg={"chat":{"id":100,"type":"private"},"from":{"id":100}}
            question="Подробно проанализируй изменения общения с Иваном"
            await main.private_message({**msg,"text":"/deep "+question})
            self.assertIn("Подтверждение",sent.await_args.args[1])
            self.assertEqual(len(tasks),0)
            code=main.PENDING_ANALYSES[100]["code"]
            await main.private_message({**msg,"text":"/confirm wrong"})
            self.assertEqual(len(tasks),0)
            await main.private_message({**msg,"text":"/confirm "+code})
            self.assertEqual(len(tasks),1)
            self.assertNotIn(100,main.PENDING_ANALYSES)
            await tasks.pop()
            self.assertIn("Разбор готов",long_sent.await_args.args[1])
            self.assertFalse(main.PREMIUM_AUTHORIZED.get())

    async def test_usage_and_model_commands_owner_only(self):
        with patch.object(main,"BOT_OWNER_ID","100"), \
             patch.object(main,"send_text",new_callable=AsyncMock) as sent, \
             patch.object(main,"send_long_text",new_callable=AsyncMock) as long_sent:
            unauthorized={"chat":{"id":999,"type":"private"},"from":{"id":999},"text":"/model"}
            await main.private_message(unauthorized)
            self.assertIn("Доступ закрыт",sent.await_args.args[1])
            await main.private_message({"chat":{"id":100,"type":"private"},
                                        "from":{"id":100},"text":"/model"})
            self.assertIn("gpt-5.4-nano",sent.await_args.args[1])
            await main.private_message({"chat":{"id":100,"type":"private"},
                                        "from":{"id":100},"text":"/usage"})
            self.assertIn("Учёт OpenAI API",long_sent.await_args.args[1])


if __name__=="__main__":
    unittest.main()
