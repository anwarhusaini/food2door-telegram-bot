#!/usr/bin/env python3
"""
Food2Door Telegram Bot - Vercel Serverless Function
Endpoint: POST /api/bot
"""

import json
import asyncio
import threading
import os

# Telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Config from env
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8935028631:AAFPDx1DzJmbfQg-_J44dyKgxE7XrYdEaaY")
ORDER_GROUP = os.environ.get("ORDER_GROUP", "@f2d_order")
KITCHEN_GROUP = os.environ.get("KITCHEN_GROUP", "@f2d_kitchen")

# Global app cache
_app = None

def get_app():
    global _app
    if _app is None:
        _app = Application.builder().token(BOT_TOKEN).build()
        _app.add_handler(CommandHandler("start", start_command))
        _app.add_handler(CommandHandler("status", status_command))
        _app.add_handler(CallbackQueryHandler(button_callback))
    return _app

def start_command(update, context):
    from datetime import datetime
    import hashlib, sqlite3
    
    order_number = f"F2D-{datetime.now().strftime('%Y%m%d')}-{hashlib.md5(str(update.effective_user.id).encode()).hexdigest()[:3].upper()}"
    
    conn = sqlite3.connect("/tmp/food2door.db")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, order_number TEXT, customer_name TEXT, phone TEXT, delivery_address TEXT, order_type TEXT, payment_method TEXT, status TEXT, order_date TEXT)")
    cursor.execute("INSERT OR IGNORE INTO orders (order_number, customer_name, phone, delivery_address, order_type, payment_method, status) VALUES (?, 'New Customer', '+977 9812345678', 'Kathmandu', 'Delivery', 'Cash', 'New')", (order_number,))
    order_id = cursor.lastrowid
    
    cursor.execute("CREATE TABLE IF NOT EXISTS telegram_order_status (order_id INTEGER PRIMARY KEY, current_status TEXT, last_checked_by TEXT, last_transition_at TEXT)")
    cursor.execute("INSERT OR REPLACE INTO telegram_order_status (order_id, current_status) VALUES (?, 'New')", (order_id,))
    conn.commit()
    conn.close()
    
    keyboard = [[InlineKeyboardButton("Start Prep", callback_data="prep")]]
    update.message.reply_text(f"\U0001F680 New order! #{order_number}\nStatus: New", reply_markup=InlineKeyboardMarkup(keyboard))

def button_callback(update, context):
    query = update.callback_query
    query.answer()
    data = query.data
    user = query.from_user.first_name
    order_id = query.from_user.id
    
    import sqlite3
    conn = sqlite3.connect("/tmp/food2door.db")
    cursor = conn.cursor()
    cursor.execute("SELECT current_status FROM telegram_order_status WHERE order_id = ?", (order_id,))
    row = cursor.fetchone()
    current = row[0] if row else "New"
    conn.close()
    
    transitions = {"New": "Prep", "Prep": "Out", "Out": "Done"}
    expected = transitions.get(current)
    
    if data == expected or (data == "Done" and current == "Out"):
        new_status = data
        conn = sqlite3.connect("/tmp/food2door.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE telegram_order_status SET current_status = ?, last_checked_by = ?, last_transition_at = datetime('now') WHERE order_id = ?", (new_status, user, order_id))
        cursor.execute("UPDATE orders SET status = ? WHERE id = ?", (new_status, order_id))
        conn.commit()
        conn.close()
        
        keyboards = {"New": [[InlineKeyboardButton("Start Prep", callback_data="prep")]], "Prep": [[InlineKeyboardButton("Mark Out", callback_data="out")]], "Out": [[InlineKeyboardButton("Mark Done", callback_data="done")]], "Done": []}
        query.edit_message_text(f"\u2705 {new_status}", reply_markup=InlineKeyboardMarkup(keyboards.get(new_status, [])))
        
        if new_status == "Prep":
            context.bot.send_message(chat_id=KITCHEN_GROUP, text=f"\U0001F374 New order to prep! #{order_id}")
        if new_status == "Done":
            context.bot.send_message(chat_id=ORDER_GROUP, text=f"\u2705 Order #{order_id} done!")
    else:
        query.edit_message_text(f"\u274C Invalid: {current} -> {data}")

def status_command(update, context):
    import sqlite3
    conn = sqlite3.connect("/tmp/food2door.db")
    cursor = conn.cursor()
    cursor.execute("SELECT order_number, status FROM orders WHERE status != 'Done' LIMIT 5")
    rows = cursor.fetchall()
    conn.close()
    text = "\U0001F4CB Active:\n" + "\n".join([f"- {r[0]}: {r[1]}" for r in rows]) if rows else "None"
    update.message.reply_text(text)

def handler(request):
    app = get_app()
    if request.method != "POST":
        return {"statusCode": 405, "body": "Method not allowed"}
    
    try:
        body = request.body if hasattr(request, "body") else request.read()
        update_data = json.loads(body.decode("utf-8"))
        update = Update.de_json(update_data, app.bot)
        
        def process():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(app.process_update(update))
            finally:
                loop.close()
        
        t = threading.Thread(target=process)
        t.start()
        t.join(timeout=8)
        return {"statusCode": 200, "body": json.dumps({"ok": True})}
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
