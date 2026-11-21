"""Private owner-approved browser bridge to the Telegram Business archive.

This is a *browser* interface, not an automatic ChatGPT memory connection.
The owner can issue a revocable read-only secret link for browsers that cannot
persist cookies. The link grants access only to its holder; nothing is public.
"""
import hashlib
import hmac
import html
import secrets
import time
from datetime import datetime
from urllib.parse import parse_qs, quote, urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

PAIRING_TTL_SECONDS=10*60
SESSION_TTL_SECONDS=30*86400
COOKIE_NAME="alexey_bridge_session"
READ_LINK_QUERY="access"


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def create_login_code(db):
    """Return an owner-only code. Store a *hash*, not the usable code."""
    code=secrets.token_urlsafe(24)
    now=int(time.time())
    with db() as c:
        c.execute("DELETE FROM bridge_login_codes")
        c.execute("""INSERT INTO bridge_login_codes(code_hash,created_at,expires_at)
            VALUES(?,?,?)""",(_hash(code),now,now+PAIRING_TTL_SECONDS))
        c.execute("DELETE FROM bridge_sessions WHERE expires_at<?",(now,))
    return code


def redeem_login_code(db,code):
    if not isinstance(code,str) or not (20<=len(code)<=80):
        return None
    hashed=_hash(code)
    now=int(time.time())
    with db() as c:
        row=c.execute("""SELECT code_hash FROM bridge_login_codes
            WHERE code_hash=? AND expires_at>?""",(hashed,now)).fetchone()
        if row is None:return None
        # A one-time code cannot be used by another session after redeeming.
        c.execute("DELETE FROM bridge_login_codes WHERE code_hash=?",(hashed,))
        session=secrets.token_urlsafe(32)
        csrf=secrets.token_urlsafe(24)
        c.execute("""INSERT INTO bridge_sessions(session_hash,csrf_token,created_at,expires_at)
            VALUES(?,?,?,?)""",(_hash(session),csrf,now,now+SESSION_TTL_SECONDS))
    return session


def create_read_link(db,base_url):
    """Generate a long-lived read-only bearer URL, replacing any earlier link.

    The secret is returned only to the Telegram owner. Only its hash is stored.
    """
    token=secrets.token_urlsafe(48)
    now=int(time.time())
    with db() as c:
        c.execute("""INSERT INTO bridge_read_keys(key_id,token_hash,created_at)
            VALUES(1,?,?) ON CONFLICT(key_id) DO UPDATE SET
            token_hash=excluded.token_hash, created_at=excluded.created_at""",
            (_hash(token),now))
    return base_url.rstrip("/")+"/bridge?"+urlencode({READ_LINK_QUERY:token})


def revoke_read_link(db):
    """Immediately disable any direct read link."""
    with db() as c:
        c.execute("DELETE FROM bridge_read_keys")


def _escape(text):
    return html.escape(str(text if text is not None else ""),quote=True)


def _stamp(when,zone):
    if not when:return "нет данных"
    return datetime.fromtimestamp(int(when),zone).strftime("%d.%m.%Y %H:%M")


def _html(title,body):
    page=f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{_escape(title)} | Alexey AI</title>
<style>
:root{{color-scheme:dark}}*{{box-sizing:border-box}}body{{margin:0;background:#111419;color:#f1f1f2;
font:16px system-ui,-apple-system,Segoe UI,sans-serif;line-height:1.5}}
main{{max-width:890px;margin:0 auto;padding:26px 18px 80px}}
h1{{font-size:1.8rem}}h2{{font-size:1.2rem;margin-top:32px}}nav{{display:flex;gap:12px;flex-wrap:wrap;
align-items:center;padding:14px 0;border-bottom:1px solid #353a42;margin-bottom:24px}}
a{{color:#a5c9ff}}nav a{{text-decoration:none}}.card{{background:#1d2229;border:1px solid #343942;
border-radius:14px;padding:16px;margin:14px 0;overflow-wrap:anywhere}}small,.muted{{color:#acb2bd}}
pre{{white-space:pre-wrap;word-break:break-word;margin:0;font:inherit}}input,textarea,button{{
font:inherit;border-radius:8px;border:1px solid #515967;padding:10px 12px;background:#252c34;
color:#fff}}input,textarea{{width:100%}}textarea{{min-height:130px}}button{{cursor:pointer;background:#346ac3;
border-color:#346ac3}}label{{display:block;margin-top:12px;margin-bottom:5px}}form{{margin:8px 0}}
.btnlink{{background:none;border:0;padding:0;text-decoration:underline;color:#a5c9ff}}
.pagination{{display:flex;gap:20px;margin-top:18px}}.warn{{color:#f7c989}}.date{{font-size:.84rem}}
</style></head><body><main>{body}</main></body></html>"""
    resp=HTMLResponse(page)
    resp.headers["Cache-Control"]="no-store, max-age=0"
    resp.headers["Pragma"]="no-cache"
    resp.headers["Referrer-Policy"]="no-referrer"
    resp.headers["X-Content-Type-Options"]="nosniff"
    resp.headers["X-Frame-Options"]="DENY"
    resp.headers["Content-Security-Policy"]="default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    return resp


def _form_parse(raw,max_size=12000):
    if len(raw)>max_size:raise HTTPException(413,"Form too large")
    try:
        decoded=raw.decode("utf-8",errors="strict")
        params=parse_qs(decoded,keep_blank_values=True,strict_parsing=False)
    except (UnicodeDecodeError,ValueError):
        raise HTTPException(400,"Invalid form")
    return {k:v[0] for k,v in params.items() if v}


def make_router(db,zone,add_note):
    router=APIRouter()

    def session_for(request):
        token=request.cookies.get(COOKIE_NAME)
        if token and len(token)<=160:
            with db() as c:
                session=c.execute("""SELECT session_hash,csrf_token,expires_at
                    FROM bridge_sessions WHERE session_hash=? AND expires_at>?""",
                    (_hash(token),int(time.time()))).fetchone()
            if session is not None:return session
        # Direct links are limited to safe GET requests. Never grant POST/notes
        # write access using a read-link secret, even with a forged CSRF token.
        if request.method!="GET":return None
        access=request.query_params.get(READ_LINK_QUERY,"")
        if not 40<=len(access)<=120:return None
        with db() as c:
            entry=c.execute("SELECT token_hash FROM bridge_read_keys WHERE key_id=1").fetchone()
        if entry and hmac.compare_digest(entry["token_hash"],_hash(access)):
            return {"csrf_token":"","readonly":True}
        return None

    def url(request,path,**params):
        """Preserve the read-link secret only inside this same-origin portal."""
        access=request.query_params.get(READ_LINK_QUERY)
        if access and session_for(request) is not None:
            params[READ_LINK_QUERY]=access
        return path+("?"+urlencode(params) if params else "")

    def read_hidden(request):
        access=request.query_params.get(READ_LINK_QUERY)
        if access and session_for(request) is not None:
            return f'<input type="hidden" name="{READ_LINK_QUERY}" value="{_escape(access)}">'
        return ""

    def require(request):
        session=session_for(request)
        if session is None:
            raise HTTPException(status_code=401,detail="Sign in using Telegram /sync_link")
        return session

    def nav(request):
        links=[("Главная","/bridge"),("Чаты","/bridge/chats"),
               ("Поиск","/bridge/search"),("Заметки","/bridge/notes"),
               ("Состояние","/bridge/status")]
        content='<nav><strong>🐗 Alexey AI</strong>'
        for label,path in links:
            content+=f'<a href="{_escape(url(request,path))}">{label}</a>'
        if not (isinstance(session_for(request),dict) and session_for(request).get("readonly")):
            content+=('<form action="/bridge/logout" method="post" style="margin:0">'
                      '<button type="submit" class="btnlink">Выйти</button></form>')
        return content+"</nav>"

    def page(request,title,body):
        return _html(title,nav(request)+body)

    def login_page(error=""):
        msg=f'<p class="warn">{_escape(error)}</p>' if error else ""
        return _html("Вход",f"""<h1>🐗 Alexey AI - приватный архив</h1>
<p>Для доступа к архиву без постоянного входа отправь <code>/sync_link</code> боту
<a href="https://t.me/aialexey11_bot" target="_blank" rel="noopener noreferrer">@aialexey11_bot</a>
со своего Telegram-аккаунта владельца. Он выдаст персональную закрытую ссылку.
Её нельзя публиковать: любой обладатель ссылки может читать архив.</p>
{msg}
<form method="post" action="/bridge/login">
<label for="code">Одноразовый код из Telegram</label>
<input id="code" name="code" autocomplete="off" spellcheck="false" required maxlength="80">
<p><button type="submit">Подключить</button></p></form>
<p class="muted">Старый вход по одноразовому коду оставлен только для ранее выданных кодов.
Закрытая ссылка действует до /sync_revoke или следующей выдачи /sync_link.
Не передавай её посторонним. Чтение архива по ссылке разрешено без cookie; запись заметок по ней запрещена.</p>""")

    @router.get("/bridge")
    async def portal_root(request:Request):
        if session_for(request) is None:return login_page()
        with db() as c:
            messages=c.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            chats=c.execute("SELECT COUNT(DISTINCT chat_id) FROM messages").fetchone()[0]
            notes=c.execute("SELECT COUNT(*) FROM shared_notes").fetchone()[0]
            last=c.execute("SELECT MAX(message_date) FROM messages").fetchone()[0]
        body=("<h1>Личный Telegram-архив</h1>"
              "<p>Подключён защищённый браузерный доступ. Здесь нет автоматической загрузки в память ChatGPT.</p>"
              f"<div class=card>Сообщений: <b>{messages}</b><br>Чатов: <b>{chats}</b><br>"
              f"Заметок: <b>{notes}</b><br>Дата последнего сообщения: <b>{_stamp(last,zone)}</b></div>"
              f'<p><a href="{_escape(url(request,"/bridge/chats"))}">Открыть чаты</a> · '
              f'<a href="{_escape(url(request,"/bridge/search"))}">Найти сообщение</a> · '
              f'<a href="{_escape(url(request,"/bridge/notes"))}">Общие заметки</a></p>')
        return page(request,"Главная",body)

    @router.post("/bridge/login")
    async def portal_login(request:Request):
        if not request.headers.get("content-type","").startswith("application/x-www-form-urlencoded"):
            raise HTTPException(415,"Unsupported form")
        form=_form_parse(await request.body(),2048)
        session=redeem_login_code(db,form.get("code",""))
        if session is None:return login_page("Неверный или просроченный код. Запроси новый через /sync_link.")
        response=RedirectResponse("/bridge",status_code=303)
        response.set_cookie(COOKIE_NAME,session,max_age=SESSION_TTL_SECONDS,
                            secure=True,httponly=True,samesite="lax",path="/bridge")
        response.headers["Cache-Control"]="no-store"
        return response

    @router.post("/bridge/logout")
    async def portal_logout(request:Request):
        token=request.cookies.get(COOKIE_NAME)
        if token:
            with db() as c:
                c.execute("DELETE FROM bridge_sessions WHERE session_hash=?",(_hash(token),))
        response=RedirectResponse("/bridge",status_code=303)
        response.delete_cookie(COOKIE_NAME,path="/bridge",secure=True,httponly=True,samesite="lax")
        return response

    @router.get("/bridge/status")
    async def portal_status(request:Request):
        require(request)
        with db() as c:
            conn=c.execute("SELECT COUNT(*) AS n, COALESCE(SUM(is_enabled),0) AS active FROM business_connections").fetchone()
            latest=c.execute("""SELECT MAX(received_at) AS at FROM diagnostic_chat_activity""").fetchone()["at"]
            photos=c.execute("SELECT COUNT(*) FROM archived_photos").fetchone()[0]
            edits=c.execute("SELECT COUNT(*) FROM message_edits").fetchone()[0]
            mt=c.execute("SELECT COUNT(*) FROM mtproto_photos").fetchone()[0]
        return page(request,"Статус",f'<h1>Состояние архива</h1><div class="card">'
                    f"Business подключений: {_escape(conn['active'])}/{_escape(conn['n'])}<br>"
                    f"Последнее событие получено: {_stamp(latest,zone)}<br>"
                    f"Сохранено фотографий: {photos}<br>Редактирований: {edits}<br>"
                    f"Исчезающих фото MTProto: {mt}</div>"
                    '<p class="muted">Статистика доступных данных, а не гарантия полного охвата Telegram.</p>')

    @router.get("/bridge/chats")
    async def portal_chats(request:Request,q:str="",page_no:int=1):
        require(request)
        page_no=max(1,min(page_no,1000))
        search=(q or "").strip()[:80]
        with db() as c:
            args=[]
            cond=""
            if search:
                cond="WHERE unicode_lower(chat_title) LIKE ?"
                args.append("%"+search.casefold()+"%")
            rows=c.execute(f"""SELECT chat_id,MAX(chat_title) AS title,COUNT(*) AS n,
                MAX(message_date) AS last_at
                FROM messages {cond}
                GROUP BY chat_id ORDER BY last_at DESC LIMIT 50 OFFSET ?""",
                (*args,(page_no-1)*50)).fetchall()
        parts=['<h1>Чаты в архиве</h1>',
               '<form method="get" action="/bridge/chats"><label>Найти по имени чата</label>',
               read_hidden(request),
               f'<input name="q" value="{_escape(search)}"><p><button>Найти</button></p></form>']
        for row in rows:
            parts.append(f'<div class="card"><a href="{_escape(url(request,"/bridge/chat/"+str(row["chat_id"])))}">'
                         f'{_escape(row["title"] or row["chat_id"])}</a> '
                         f'<small>ID {row["chat_id"]} · {row["n"]} сообщений · '
                         f'{_stamp(row["last_at"],zone)}</small></div>')
        if not rows:parts.append("<p>Подходящих чатов нет.</p>")
        if len(rows)>=50:
            parts.append(f'<a href="{_escape(url(request,"/bridge/chats",q=search,page_no=page_no+1))}">Следующая страница</a>')
        return page(request,"Чаты","".join(parts))

    @router.get("/bridge/chat/{chat_id}")
    async def portal_chat(request:Request,chat_id:int,page_no:int=1):
        require(request)
        page_no=max(1,min(page_no,1000))
        with db() as c:
            rows=c.execute("""SELECT message_id,message_date,sender_name,text,deleted,edited,chat_title
                FROM messages WHERE chat_id=? ORDER BY message_date DESC,id DESC
                LIMIT 60 OFFSET ?""",(chat_id,(page_no-1)*60)).fetchall()
        parts=[f"<h1>Чат {_escape(rows[0]['chat_title'] if rows else chat_id)}</h1>",
               f"<p class=muted>ID {chat_id} · страница {page_no}. "
               "Сначала новые сообщения.</p>"]
        for row in rows:
            flags=(" · удалено" if row["deleted"] else "")+(" · редактировано" if row["edited"] else "")
            parts.append('<div class="card">'
                         f'<small>{_stamp(row["message_date"],zone)} · '
                         f'{_escape(row["sender_name"] or "Неизвестно")} · '
                         f'#{row["message_id"]}{flags}</small>'
                         f'<pre>{_escape(row["text"])}</pre></div>')
        if not rows:parts.append("<p>Нет сообщений на этой странице.</p>")
        if len(rows)==60:
            parts.append(f'<a href="{_escape(url(request,"/bridge/chat/"+str(chat_id),page_no=page_no+1))}">Сообщения раньше</a>')
        return page(request,"Переписка","".join(parts))

    @router.get("/bridge/search")
    async def portal_search(request:Request,q:str=""):
        require(request)
        term=q.strip()[:120]
        parts=[]
        parts.append('<h1>Поиск по архиву</h1>')
        parts.append('<form action="/bridge/search" method="get">')
        parts.append(read_hidden(request))
        parts.append('<label>Слово или фраза</label>')
        parts.append(f'<input name="q" value="{_escape(term)}">')
        parts.append('<p><button>Найти</button></p></form>')
        if term:
            with db() as c:
                rows=c.execute("""SELECT chat_id,chat_title,message_id,message_date,
                    sender_name,text FROM messages WHERE
                    unicode_lower(text) LIKE ? OR unicode_lower(chat_title) LIKE ?
                    ORDER BY message_date DESC,id DESC LIMIT 50""",
                    ("%"+term.casefold()+"%","%"+term.casefold()+"%")).fetchall()
            parts.append(f"<p>Показано совпадений: {len(rows)} (максимум 50)</p>")
            for row in rows:
                preview=(row["text"] or "")[:1300]
                parts.append('<div class="card">'
                             f'<a href="{_escape(url(request,"/bridge/chat/"+str(row["chat_id"])))}">{_escape(row["chat_title"])}</a> '
                             f'<small>#{row["message_id"]} · '
                             f'{_stamp(row["message_date"],zone)} · '
                             f'{_escape(row["sender_name"])}</small>'
                             f'<pre>{_escape(preview)}</pre></div>')
        return page(request,"Поиск","".join(parts))

    @router.get("/bridge/notes")
    async def portal_notes(request:Request):
        session=require(request)
        with db() as c:
            notes=c.execute("""SELECT id,subject,content,created_at,source
                FROM shared_notes ORDER BY id DESC LIMIT 100""").fetchall()
        parts=['<h1>Общие заметки</h1>',
               '<p class="muted">Записанные здесь факты можно читать из Telegram через /sync_notes. '
               'Никакой записи во внутреннюю память ChatGPT не происходит.</p>',
               ]
        if not (isinstance(session,dict) and session.get("readonly")):
            parts.extend([
               '<form action="/bridge/notes" method="post" class="card">',
               f'<input name="csrf" type="hidden" value="{_escape(session["csrf_token"])}">',
               '<label>Название</label><input name="subject" maxlength="150" required>',
               '<label>Текст заметки</label><textarea name="content" maxlength="8000" required></textarea>',
               '<p><button>Сохранить общую заметку</button></p></form>'])
        for r in notes:
            parts.append(f'<div class="card"><small>#{r["id"]} · '
                         f'{_stamp(r["created_at"],zone)} · {_escape(r["source"])}</small>'
                         f'<h2>{_escape(r["subject"])}</h2><pre>{_escape(r["content"])}</pre></div>')
        return page(request,"Заметки","".join(parts))

    @router.post("/bridge/notes")
    async def portal_add_note(request:Request):
        session=require(request)
        if not request.headers.get("content-type","").startswith("application/x-www-form-urlencoded"):
            raise HTTPException(415,"Unsupported form")
        form=_form_parse(await request.body(),11500)
        if not hmac.compare_digest(form.get("csrf",""),session["csrf_token"]):
            raise HTTPException(403,"Invalid CSRF")
        try:
            add_note(form.get("subject",""),form.get("content",""),source="chatgpt")
        except ValueError as exc:
            return page(request,"Ошибка",f'<p>{_escape(exc)}</p><p><a href="/bridge/notes">Назад</a></p>')
        return RedirectResponse("/bridge/notes",status_code=303)

    return router
