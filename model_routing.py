"""Explicit and auditable OpenAI model routing for Alexey AI.

Prices in USD per 1M text tokens (standard OpenAI API prices,
checked 2026-11-21). Estimates exclude taxes and possible later changes.
"""
import math
import re

NANO="gpt-5.4-nano"
MINI="gpt-5.4-mini"
PREMIUM="gpt-5.4"

MODEL_BY_TIER={"simple":NANO, "analysis":MINI, "premium":PREMIUM}
# (uncached input, cached input, output), USD per million tokens.
PRICES={
    NANO:(0.20,0.02,1.25),
    MINI:(0.75,0.075,4.50),
    PREMIUM:(2.50,0.25,15.00),
}

def model_for_tier(tier):
    """Fail closed: no arbitrary model names or expensive fallback."""
    try:return MODEL_BY_TIER[tier]
    except KeyError:raise ValueError("Unknown AI model tier") from None

_ANALYTICAL=re.compile(
    r"анализ|проанализ|сравн|сопостав|оцен[ик]|детальн|подробн|"
    r"отношени|эмоци|чувств|динамик|характер|вывод|тенденц|закономерн|"
    r"противореч|намерени|объясни|почему|как менял|резюмир|обобщ|"
    r"самый важн|лучший день|худший день|всё о|всю истор|"
    r"доказател|расклад|переписк[аиу] целик",
    re.IGNORECASE,
)
_SIMPLE=re.compile(
    r"^(?:привет|спасибо|здравствуй|доброе утро|"
    r"найди|поищи|покажи|напомни|кто|когда|где|сколько|"
    r"что было|что писал|что говор|какой|какая|какие|"
    r"в каком|во сколько)\b",
    re.IGNORECASE,
)

def route_question(question):
    """Conservative routing: complex/uncertain questions stay on Mini.

    Premium is NEVER assigned by classification or quoted content.
    It requires the owner-only /deep + /confirm workflow.
    """
    if not isinstance(question,str):return "analysis"
    q=question.strip()
    if len(q)>230 or _ANALYTICAL.search(q):return "analysis"
    if q and len(q)<=180 and _SIMPLE.search(q):return "simple"
    return "analysis"

def token_cost_usd(model,input_tokens,output_tokens,cached_input_tokens=0):
    """Cost estimate based on usage returned by Responses API."""
    if model not in PRICES:raise ValueError("Unpriced AI model")
    inp=max(0,int(input_tokens))
    out=max(0,int(output_tokens))
    cached=max(0,min(inp,int(cached_input_tokens)))
    base,cache,output=PRICES[model]
    return ((inp-cached)*base+cached*cache+out*output)/1_000_000

def projected_cost_usd(model,input_characters,max_output_tokens):
    """Pre-request heuristic, NOT a guaranteed max charge."""
    estimated_input=math.ceil(max(0,int(input_characters))/2)+500
    return token_cost_usd(model,estimated_input,max_output_tokens)

def model_status_text():
    lines=["🤖 Маршрутизация моделей Alexey AI",
           f"Простой запрос → {NANO}",
           f"Анализ переписок, отчёты → {MINI}",
           f"По /deep и /confirm → {PREMIUM}",
           "",
           "Цена за 1 млн токенов (вход / кешированный вход / выход):"]
    for model in (NANO,MINI,PREMIUM):
        p=PRICES[model]
        lines.append(f"• {model}: USD {p[0]:.2f} / USD {p[1]:.3f} / USD {p[2]:.2f}")
    lines.append("Сложные вопросы без /deep не переключают бот на дорогую модель.")
    lines.append("Расходы: /usage. Углублённый запрос: /deep ТВОЙ ВОПРОС.")
    return "\n".join(lines)
