"""Create an owner-authorized Telegram StringSession on a PRIVATE computer.

Never paste the session into chats, commits, tickets or logs. Its possession
grants account access. Revoke via Telegram Settings > Devices if compromised.
"""
import asyncio
import getpass
import os

from telethon import TelegramClient
from telethon.sessions import StringSession


async def main():
    api_id=os.getenv("TELEGRAM_API_ID","").strip()
    api_hash=os.getenv("TELEGRAM_API_HASH","").strip()
    if not api_id.isdigit() or not api_hash:
        raise SystemExit("Set TELEGRAM_API_ID and TELEGRAM_API_HASH first.")
    print("Authorization runs locally; never share the resulting session string.")
    client=TelegramClient(StringSession(),int(api_id),api_hash)
    try:
        await client.start(
            phone=lambda: input("Telegram phone (international format): ").strip(),
            code_callback=lambda: input("Telegram login code: ").strip(),
            password=lambda: getpass.getpass("Telegram 2FA password (if requested): "))
        me=await client.get_me()
        print(f"\nAuthenticated user ID: {me.id}")
        print("\nCopy this confidential value into Railway TELEGRAM_SESSION:")
        print(client.session.save())
        print("\nTreat this like a password. Do not paste it into ChatGPT or GitHub.")
    finally:
        await client.disconnect()


if __name__=="__main__":
    asyncio.run(main())
