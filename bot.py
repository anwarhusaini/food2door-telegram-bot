#!/usr/bin/env python3
"""
Food2Door Telegram Order Tracking Bot
Runs on Render as a background worker (polling mode)
"""

import os
import sqlite3
import asyncio
import hashlib
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Configuration
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ORDER_GROUP = os.environ.get("ORDER_GROUP", "@f2d_order")
KITCHEN_GROUP = os.environ.get("KITCHEN_GROUP", "@f2d_kitchen")
DATABASE_PATH = os.environ.get("DATABASE_PATH", "/tmp/food2door.db")

print(f"Starting Food2Door Bot...")
print(f"Bot Token: {'***' if BOT_TOKEN else 'NOT SET'}")
print(f"Order Group: {ORDER_GROUP}")
print(f"Kitchen Group: {KITCHEN_GROUP}")
print(f"Database: {DATABASE_PATH}")

def get_db():
    """Get SQLite database connection"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database tables if they don't exist"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number TEXT UNIQUE,
            customer_name TEXT,
            phone TEXT,
            delivery_address TEXT,
            order_type TEXT,
            payment_method TEXT,
            status TEXT DEFAULT 'New',
            order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS telegram_order_status (
            order_id INTEGER PRIMARY KEY,
            current_status TEXT DEFAULT 'New',
            last_checked_by TEXT,
            last_transition_at TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
        )
    """)
    
    conn.commit()
    conn.close()
    print("Database initialized")

def init_order_in_db(order_number):
    """Initialize a new order in the database"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM orders WHERE order_number = ?", (order_number,))
    if cursor.fetchone():
        order_id = cursor.fetchone()["id"]
        conn.close()
        return order_id
    
    cursor.execute(
        """INSERT INTO orders 
           (order_number, customer_name, phone, delivery_address, order_type, payment_method, status, order_date) 
           VALUES (?, ?, ?, ?, ?, ?, 'New', datetime('now'))""",
        (order_number, "New Customer", "+601****6789", "Address pending", "Delivery", "Cash")
    )
    order_id = cursor.lastrowid
    cursor.execute(
        "INSERT INTO telegram_order_status (order_id, current_status) VALUES (?, 'New')",
        (order_id,)
    )
    conn.commit()
    conn.close()
    return order_id

def get_telegram_status(order_id):
    """Get current order status from telegram_order_status table"""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT current_status FROM telegram_order_status WHERE order_id = ?",
            (order_id,)
        )
        row = cursor.fetchone()
        if row:
            conn.close()
            return row[0]
    except Exception as e:
        print(f"Error getting status: {e}")
    conn.close()
    return "Unknown"

def update_telegram_status(order_id, new_status, checked_by="System"):
    """Update Telegram-specific status"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO telegram_order_status (order_id, current_status, last_checked_by, last_transition_at) 
           VALUES (?, ?, ?, datetime('now')) 
           ON CONFLICT(order_id) DO UPDATE SET 
               current_status = excluded.current_status,
               last_checked_by = excluded.last_checked_by,
               last_transition_at = datetime('now')""",
        (order_id, new_status, checked_by)
    )
    cursor.execute("UPDATE orders SET status = ? WHERE id = ?", (new_status, order_id))
    conn.commit()
    conn.close()

def next_keyboard(status):
    """Generate inline keyboard based on current status"""
    keyboards = {
        "New": [[InlineKeyboardButton("Start Prep", callback_data="prep")]],
        "Prep": [[InlineKeyboardButton("Mark Out", callback_data="out")]],
        "Out": [[InlineKeyboardButton("Mark Done", callback_data="done")]],
        "Done": []
    }
    keyboard = keyboards.get(status, [[InlineKeyboardButton("Start Prep", callback_data="prep")]])
    return InlineKeyboardMarkup(keyboard)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command - create a new order"""
    user_id = update.effective_user.id
    order_number = f"F2D-{datetime.now().strftime('%Y%m%d')}-{hashlib.md5(str(user_id).encode()).hexdigest()[:3].upper()}"
    
    order_id = init_order_in_db(order_number)
    update_telegram_status(order_id, "New", f"{update.effective_user.first_name} (Telegram)")
    
    tg_status = get_telegram_status(order_id)
    keyboard = next_keyboard(tg_status)
    
    text = (
        f"🚀 New order created!\n"
        f"Order #: {order_number}\n"
        f"Current status: New\n"
        f"Click a button below to update status:"
    )
    await update.message.reply_text(text, reply_markup=keyboard)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button presses"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user = query.from_user.first_name
    order_id = query.from_user.id
    current = get_telegram_status(order_id)
    
    transitions = {
        "New": "prep",
        "Prep": "out", 
        "Out": "done"
    }
    
    expected_next = transitions.get(current)
    
    if (data == expected_next) or (data == "done" and current == "Out"):
        status_map = {"prep": "Prep", "out": "Out", "done": "Done"}
        new_status = status_map.get(data, data.capitalize())
        
        update_telegram_status(order_id, new_status, user)
        keyboard = next_keyboard(new_status)
        
        if new_status == "Done":
            new_text = f"✅ Order status updated to: {new_status.upper()}\n🎉 Order complete!"
            
            try:
                await context.bot.send_message(
                    chat_id=ORDER_GROUP,
                    text=f"✅ Order #{order_id} marked as **Done**. All tasks complete."
                )
            except Exception as e:
                print(f"Error notifying order group: {e}")
        else:
            new_text = f"✅ Order status updated to: {new_status.upper()}"
            
            if new_status == "Prep":
                try:
                    kitchen_text = (
                        f"🍳 *NEW ORDER TO PREP*\n\n"
                        f"Order #: {order_id}\n"
                        f"Status: {new_status}\n"
                        f"⚠️ Atan/Bella has started prep. Cook staff please mark as 'Out' when complete."
                    )
                    await context.bot.send_message(
                        chat_id=KITCHEN_GROUP,
                        text=kitchen_text
                    )
                except Exception as e:
                    print(f"Error notifying kitchen: {e}")
        
        await query.edit_message_text(text=new_text, reply_markup=keyboard)
    else:
        expected_text = expected_next.upper() if expected_next else "N/A"
        error_text = (
            f"❌ Invalid transition from **{current}** to **{data.upper()}**.\n\n"
            f"Expected next step: {expected_text}"
        )
        await query.edit_message_text(text=error_text, reply_markup=next_keyboard(current))

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current order status"""
    user_id = update.effective_user.id
    status = get_telegram_status(user_id)
    
    if status == "Unknown":
        await update.message.reply_text("No order found for your account. Use /start to create one.")
    else:
        keyboard = next_keyboard(status)
        await update.message.reply_text(
            f"📋 Your current order status: **{status}**",
            reply_markup=keyboard
        )

def main():
    """Main entry point - start the bot"""
    print("Initializing Food2Door Telegram Bot...")
    
    init_db()
    
    if not BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN not set!")
        return
    
    print("Creating Telegram application...")
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    print("Application created with handlers")
    print("Starting polling...")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
