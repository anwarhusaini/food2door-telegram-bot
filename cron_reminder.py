#!/usr/bin/env python3
"""Cron reminder for Food2Door Telegram orders that get stuck"""

import os
import sqlite3
import asyncio
from datetime import datetime, timedelta
from telegram import Bot
from supabase import create_client, Client

# Configuration
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8935028631:AAFPDx1DzJmbfQg-_J44dyKgxE7XrYdEaaY")
ORDER_GROUP = os.environ.get("ORDER_GROUP", "@f2d_order")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://gzzlokhsibryyflddikh.supabase.co")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "sb_publishable_key_here")
DATABASE_PATH = os.environ.get("FOOD2DOOR_DB", "/Users/anwarhusaini/food2door.db")

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

bot = Bot(token=BOT_TOKEN)

def get_stuck_orders():
    """Get orders that haven't progressed in over 10 minutes"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # Calculate the cutoff time (10 minutes ago)
    cutoff = (datetime.now() - timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S')
    
    # Query orders that are not 'Done' and haven't been updated in 10+ minutes
    cursor.execute("""
        SELECT o.id, o.order_number, o.status, tos.current_status, 
               tos.last_transition_at
        FROM orders o
        JOIN telegram_order_status tos ON o.id = tos.order_id
        WHERE o.status != 'Done'
        AND o.updated_at < ?
        AND tos.last_transition_at < ?
    """, (cutoff, cutoff))
    
    rows = cursor.fetchall()
    conn.close()
    return rows

async def send_reminder(order_id, order_number, current_status, last_checked):
    """Send a reminder message to the order group"""
    current_time = datetime.now()
    minutes_stuck = int((current_time - datetime.strptime(last_checked, '%Y-%m-%d %H:%M:%S')).total_seconds() / 60)
    
    # Determine the reminder message based on status
    status_messages = {
        "New": f"⚠️ Order *{order_number}* has been in *New* status for {minutes_stuck} minutes. Please click 'Start Prep' to continue.",
        "Prep": f"⚠️ Order *{order_number}* has been in *Prep* status for {minutes_stuck} minutes. Cook staff, please mark as 'Out' when ready.",
        "Out": f"⚠️ Order *{order_number}* has been in *Out* status for {minutes_stuck} minutes. Atan/Bella, please mark as 'Done' after delivery."
    }
    
    message = status_messages.get(current_status, f"⚠️ Order *{order_number}* has been stuck for {minutes_stuck} minutes.")
    
    await bot.send_message(
        chat_id=ORDER_GROUP,
        text=message,
        parse_mode="Markdown"
    )
    print(f"Sent reminder for order {order_number}")

async def main():
    """Main cron job function"""
    print(f"[{datetime.now()}] Checking for stuck orders...")
    
    stuck_orders = get_stuck_orders()
    
    if not stuck_orders:
        print("No stuck orders found.")
        return
    
    print(f"Found {len(stuck_orders)} stuck orders.")
    
    for row in stuck_orders:
        order_id, order_number, db_status, tg_status, last_transition = row
        try:
            await send_reminder(order_id, order_number, tg_status, last_transition or '')
        except Exception as e:
            print(f"Error sending reminder for order {order_number}: {e}")
    
    print(f"[{datetime.now()}] Check complete.")

if __name__ == "__main__":
    asyncio.run(main())
