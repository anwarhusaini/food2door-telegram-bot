#!/usr/bin/env python3
"""Food2Door Telegram Order Tracking Bot"""

import os
import sqlite3
import asyncio
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Configuration
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8935028631:AAFPDx1DzJmbfQg-_J44dyKgxE7XrYdEaaY")
ORDER_GROUP = os.environ.get("ORDER_GROUP", "@f2d_order")
KITCHEN_GROUP = os.environ.get("KITCHEN_GROUP", "@f2d_kitchen")
DATABASE_PATH = os.environ.get("FOOD2DOOR_DB", "/Users/anwarhusaini/food2door.db")

# Supabase config
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://gzzlokhsibryyflddikh.supabase.co")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "sb_publishable_key_here")

def get_db():
    """Get SQLite database connection"""
    import sqlite3
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_order_in_db(order_number):
    """Initialize a new order in the database"""
    import sqlite3
    conn = get_db()
    cursor = conn.cursor()
    # Check if order already exists
    cursor.execute("SELECT id FROM orders WHERE order_number = ?", (order_number,))
    if cursor.fetchone():
        conn.close()
        return cursor.fetchone()['id']
    
    # Create new order
    cursor.execute(
        "INSERT INTO orders (order_number, customer_name, phone, delivery_address, order_type, payment_method, status, order_date) VALUES (?, ?, ?, ?, ?, ?, 'New', datetime('now'))",
        (order_number, "New Customer", "+977 9812345678", "Kathmandu, Putalisadak", "Delivery", "Cash")
    )
    order_id = cursor.lastrowid
    
    # Initialize telegram_order_status
    cursor.execute(
        "INSERT INTO telegram_order_status (order_id, current_status) VALUES (?, 'New')",
        (order_id,)
    )
    conn.commit()
    conn.close()
    return order_id

def get_order_status(order_id):
    """Get current order status from SQLite"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM orders WHERE id = ?", (order_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0]
    return None

def update_order_status(order_id, new_status):
    """Update order status in SQLite"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE orders SET status = ? WHERE id = ?", (new_status, order_id))
    conn.commit()
    conn.close()

def get_telegram_status(order_id):
    """Get Telegram-specific status"""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT current_status FROM telegram_order_status WHERE order_id = ?", (order_id,))
        row = cursor.fetchone()
        if row:
            conn.close()
            return row[0]
    except:
        pass
    conn.close()
    return "New"

def update_telegram_status(order_id, new_status, checked_by="User"):
    """Update Telegram-specific status in SQLite"""
    conn = get_db()
    cursor = conn.cursor()
    # Upsert - insert or update
    cursor.execute(
        """INSERT INTO telegram_order_status (order_id, current_status, last_checked_by, last_transition_at) 
           VALUES (?, ?, ?, datetime('now')) 
           ON CONFLICT(order_id) DO UPDATE SET 
               current_status = excluded.current_status,
               last_checked_by = excluded.last_checked_by,
               last_transition_at = datetime('now')""",
        (order_id, new_status, checked_by)
    )
    # Also update the main orders table
    cursor.execute("UPDATE orders SET status = ? WHERE id = ?", (new_status, order_id))
    conn.commit()
    conn.close()

def next_keyboard(status):
    """Generate inline keyboard based on current status"""
    keyboards = {
        "New": [[InlineKeyboardButton("Start Prep", callback_data="prep")]],
        "Prep": [[InlineKeyboardButton("Mark Out", callback_data="out")]],
        "Out": [[InlineKeyboardButton("Mark Done", callback_data="done")]],
        "Done": []  # No buttons needed
    }
    keyboard = keyboards.get(status, [[InlineKeyboardButton("Start Prep", callback_data="prep")]])
    return InlineKeyboardMarkup(keyboard)

async def send_to_kitchen(order_id, order_number, current_status):
    """Send order to kitchen group with status"""
    import sqlite3
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT customer_name, phone, delivery_address FROM orders WHERE id = ?", (order_id,))
    row = cursor.fetchone()
    conn.close()
    
    customer_name = row[0] if row else "Unknown"
    phone = row[1] if row else "N/A"
    address = row[2] if row else "N/A"
    
    message = f"🍳 *NEW ORDER TO PREP*

"
    message += f"Order #: {order_number}
"
    message += f"Customer: {customer_name}
"
    message += f"Phone: {phone}
"
    message += f"Address: {address}
"
    message += f"Current Status: {current_status}
"
    message += f"⚠️ Atan/Bella has started prep. Cook staff please mark as 'Out' when complete."
    
    try:
        from telegram import Bot
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(
            chat_id=KITCHEN_GROUP,
            text=message,
            parse_mode="Markdown"
        )
        print(f"Sent order to kitchen group @f2d_kitchen")
    except Exception as e:
        print(f"Error sending to kitchen: {e}")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command - create a new order"""
    import hashlib
    order_number = f"F2D-{datetime.now().strftime('%Y%m%d')}-{hashlib.md5(str(update.effective_user.id).encode()).hexdigest()[:3].upper()}"
    
    order_id = init_order_in_db(order_number)
    
    # Set initial status
    update_telegram_status(order_id, "New", "System")
    
    # Get the current status for keyboard
    tg_status = get_telegram_status(order_id)
    
    keyboard = next_keyboard(tg_status)
    
    await update.message.reply_text(
        f"🆕 New order created!
"
        f"Order #: {order_number}
"
        f"Current status: New
"
        f"Group: {ORDER_GROUP}",
        reply_markup=keyboard
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button presses"""
    from telegram import CallbackQuery
    query = update.callback_query
    await query.answer()
    
    data = query.data  # "prep", "out", or "done"
    user = query.from_user.first_name
    
    # Use user ID as order identifier for simplicity
    order_id = query.from_user.id
    current = get_telegram_status(order_id)
    
    # Define valid transitions
    transitions = {
        "New": "Prep",
        "Prep": "Out",
        "Out": "Done"
    }
    
    # Check if this is a valid transition
    expected_next = transitions.get(current)
    
    if data == expected_next or (data == "Done" and current == "Out"):
        # Valid transition - update status
        new_status = data
        update_telegram_status(order_id, new_status, user)
        update_order_status(order_id, new_status)
        
        # Get new keyboard
        keyboard = next_keyboard(new_status)
        
        # Update message
        new_text = f"✅ Order status updated to: {new_status.upper()}"
        if new_status == "Done":
            new_text += "
🎉 Order complete! Ready for delivery."
        
        await query.edit_message_text(
            text=new_text,
            reply_markup=keyboard
        )
        
        # Handle status-specific actions
        if new_status == "Prep":
            # Send to kitchen group
            await send_to_kitchen(order_id, "Order #" + str(order_id)[:8], new_status)
            
        elif new_status == "Done":
            # Notify the order group that order is complete
            try:
                await context.bot.send_message(
                    chat_id=ORDER_GROUP,
                    text=f"✅ Order #{order_id} marked as **Done**. All tasks complete. Ready for delivery coordination."
                )
            except:
                pass
        
    else:
        # Invalid transition
        await query.edit_message_text(
            text=f"❌ Invalid transition from **{current}** to **{data}**.

"
                 f"Expected next step: {expected_next or 'N/A'}",
            reply_markup=next_keyboard(current),
            parse_mode="Markdown"
        )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current order status"""
    import sqlite3
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, order_number, status FROM orders WHERE status != 'Done' ORDER BY id DESC LIMIT 5")
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        await update.message.reply_text("No active orders found.")
        return
    
    text = "📋 Active orders:
"
    for row in rows:
        text += f"- Order {row[0]}: {row[1]} - {row[2]}
"
    
    await update.message.reply_text(text)

def main():
    """Start the bot"""
    print("Starting Food2Door Telegram Bot...")
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Add error handler
    async def error_handler(update, context):
        print(f"Update {update} caused error {context.error}")
    
    application.add_error_handler(error_handler)
    
    print("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
