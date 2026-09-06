#!/usr/bin/env python3
"""Food2Door Telegram Order Tracking Bot - Webhook Version for Vercel"""

import os
import sqlite3
import asyncio
import hashlib
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from functools import partial
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, WebhookAdapter

# Configuration
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8935028631:AAFPDx1DzJmbfQg-_J44dyKgxE7XrYdEaaY")
ORDER_GROUP = os.environ.get("ORDER_GROUP", "@f2d_order")
KITCHEN_GROUP = os.environ.get("KITCHEN_GROUP", "@f2d_kitchen")
DATABASE_PATH = os.environ.get("FOOD2DOOR_DB", "/Users/anwarhusaini/food2door.db")

# Supabase config  
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://gzzlokhsibryyflddikh.supabase.co")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "sb_publishable_key_here")

# Vercel-specific: webhook URL is derived from the deployment URL
WEBHOOK_URL = os.environ.get("VERCEL_URL")
if WEBHOOK_URL:
    WEBHOOK_URL = f"https://{WEBHOOK_URL}"
else:
    WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://food2door-telegram-gcgr3j6bw-anwarhusaini.vercel.app")

print(f"Webhook URL: {WEBHOOK_URL}")

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
    cursor.execute("SELECT id FROM orders WHERE order_number = ?", (order_number,))
    if cursor.fetchone():
        conn.close()
        return cursor.fetchone()["id"]
    
    cursor.execute(
        "INSERT INTO orders (order_number, customer_name, phone, delivery_address, order_type, payment_method, status, order_date) VALUES (?, ?, ?, ?, ?, ?, 'New', datetime('now'))",
        (order_number, "New Customer", "+977 9812345678", "Kathmandu, Putalisadak", "Delivery", "Cash")
    )
    order_id = cursor.lastrowid
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

async def send_to_kitchen(order_id, order_number, current_status):
    """Send order notification to kitchen group"""
    import sqlite3
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT customer_name, phone, delivery_address FROM orders WHERE id = ?", (order_id,))
    row = cursor.fetchone()
    conn.close()
    
    customer_name = row[0] if row else "Unknown"
    phone = row[1] if row else "N/A"
    address = row[2] if row else "N/A"
    
    # Get bot instance from context if available, otherwise create one
    # For webhook handler, we'll use the bot passed in
    pass  # This will be handled in the webhook handler

def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command - create a new order"""
    order_number = f"F2D-{datetime.now().strftime('%Y%m%d')}-{hashlib.md5(str(update.effective_user.id).encode()).hexdigest()[:3].upper()}"
    
    order_id = init_order_in_db(order_number)
    update_telegram_status(order_id, "New", "System")
    
    tg_status = get_telegram_status(order_id)
    keyboard = next_keyboard(tg_status)
    
    update.message.reply_text(
        f"\U0001F680 New order created!\n"
        f"Order #: {order_number}\n"
        f"Current status: New\n"
        f"Group: {ORDER_GROUP}",
        reply_markup=keyboard
    )

def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button presses"""
    query = update.callback_query
    query.answer()
    
    data = query.data
    user = query.from_user.first_name
    order_id = query.from_user.id
    current = get_telegram_status(order_id)
    
    transitions = {
        "New": "Prep",
        "Prep": "Out",
        "Out": "Done"
    }
    
    expected_next = transitions.get(current)
    
    if data == expected_next or (data == "Done" and current == "Out"):
        new_status = data
        update_telegram_status(order_id, new_status, user)
        update_order_status(order_id, new_status)
        
        keyboard = next_keyboard(new_status)
        
        new_text = f"\u2705 Order status updated to: {new_status.upper()}"
        if new_status == "Done":
            new_text += "\n\U0001F389 Order complete! Ready for delivery."
        
        query.edit_message_text(
            text=new_text,
            reply_markup=keyboard
        )
        
        # Send to kitchen if transitioning to Prep
        if new_status == "Prep":
            # Use context.bot to send message
            context.bot.send_message(
                chat_id=KITCHEN_GROUP,
                text=f"\U0001F374 *NEW ORDER TO PREP*\n\n"
                     f"Order #: {order_id}\n"
                     f"Status: {new_status}\n"
                     f"\u26A0\uFE0F Atan/Bella has started prep. Cook staff please mark as 'Out' when complete.",
            )
        
        # Notify order group if transitioning to Done
        if new_status == "Done":
            context.bot.send_message(
                chat_id=ORDER_GROUP,
                text=f"\u2705 Order #{order_id} marked as **Done**. All tasks complete.",
            )
    else:
        query.edit_message_text(
            text=f"\u274C Invalid transition from **{current}** to **{data}**.\n\n"
                 f"Expected next step: {expected_next or 'N/A'}",
            reply_markup=next_keyboard(current),
        )

def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current order status"""
    import sqlite3
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, order_number, status FROM orders WHERE status != 'Done' ORDER BY id DESC LIMIT 5")
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        update.message.reply_text("No active orders found.")
        return
    
    text = "\U0001F4CB Active orders:\n"
    for row in rows:
        text += f"- Order {row[0]}: {row[1]} - {row[2]}\n"
    
    update.message.reply_text(text)

# Create the application builder
def create_app():
    """Create and configure the Telegram application"""
    print("Creating Telegram application...")
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    print("Application created with handlers")
    return application

# Webhook server handler
class WebhookHandler(BaseHTTPRequestHandler):
    """HTTP handler for Telegram webhook updates"""
    
    application = None  # Set this from outside
    
    def do_POST(self):
        """Handle POST requests (Telegram webhook updates)"""
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        
        try:
            # Process the update through the application
            update = Update.de_json(body.decode('utf-8'), self.application.bot)
            asyncio.run(self.application.process_update(update))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok": true}')
        except Exception as e:
            print(f"Error processing update: {e}")
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'{"error": "Failed to process update"}')
    
    def log_message(self, format, *args):
        """Override to add timestamp"""
        print(f"[{datetime.now().isoformat()}] {format % args}")

def main():
    """Main entry point - creates app but runs via webhook server"""
    print("Initializing Food2Door Telegram Bot...")
    app = create_app()
    # For Vercel, we need a webhook server
    # This is handled by the Vercel routing in vercel.json
    print(f"Bot initialized. Webhook URL: {WEBHOOK_URL}")
    return app

# For Vercel serverless functions, export the handler
def handler(request):
    """Vercel serverless function handler"""
    if request.method == "POST":
        content_length = int(request.headers.get('Content-Length', 0))
        body = request.body if hasattr(request, 'body') else request.read(content_length)
        
        # Get or create app instance (cached)
        if not hasattr(handler, 'app'):
            handler.app = create_app()
            # Set up webhook on first request
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(handler.app.bot.set_webhook(
                    url=f"{WEBHOOK_URL}/api/bot",
                    secret_token="food2door_secret_123"
                ))
            except Exception as e:
                print(f"Webhook setup: {e}")
        
        try:
            import json
            update_data = json.loads(body.decode('utf-8'))
            update = Update.de_json(update_data, handler.app.bot)
            
            # Process in a thread to avoid blocking
            import threading
            def process():
                try:
                    asyncio.new_event_loop().run_until_complete(
                        handler.app.process_update(update)
                    )
                except Exception as e:
                    print(f"Process error: {e}")
            
            thread = threading.Thread(target=process)
            thread.start()
            thread.join(timeout=5)
            
            return {"statusCode": 200, "body": json.dumps({"ok": True})}
        except Exception as e:
            print(f"Handler error: {e}")
            return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
    
    return {"statusCode": 405, "body": "Method not allowed"}


# ============================================
# VERCEL SERVERLESS HANDLER
# ============================================

# Global app instance (cached for performance)
_app_instance = None

def get_app():
    """Get or create cached app instance"""
    global _app_instance
    if _app_instance is None:
        _app_instance = main()
    return _app_instance

def webhook_handler(request):
    """
    Vercel serverless function handler for /api/bot webhook
    This is called when Telegram sends an update via webhook
    """
    import json
    import asyncio
    import threading
    
    # Get app instance
    app = get_app()
    
    # Only handle POST requests (webhook updates)
    if request.method != "POST":
        return {"statusCode": 405, "body": "Method not allowed"}
    
    try:
        # Read request body
        content_length = int(request.headers.get("Content-Length", 0))
        body = request.body if hasattr(request, "body") else request.read(content_length)
        
        # Parse update
        update_data = json.loads(body.decode("utf-8"))
        
        # Process update asynchronously
        async def process_update():
            update = Update.de_json(update_data, app.bot)
            await app.process_update(update)
        
        # Run in a thread to avoid timeout
        def run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(process_update())
            finally:
                loop.close()
        
        thread = threading.Thread(target=run)
        thread.start()
        
        # Return immediately, process in background
        return {"statusCode": 200, "body": json.dumps({"ok": True})}
        
    except Exception as e:
        print(f"Webhook error: {e}")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}

# Flask-like endpoint for Vercel
def api_bot(request):
    """Handler for /api/bot endpoint"""
    return webhook_handler(request)

