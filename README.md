# Food2Door Telegram Order Tracking Bot

## Overview
This Telegram bot tracks order progress through the Prep → Out → Done workflow for Food2Door deliveries.

## Features
- 🆕 Create new orders with `/start` command
- 📋 Inline buttons for status transitions: Prep → Out → Done
- 🔔 Cron reminders if orders get stuck for 10+ minutes
- 📊 Status tracking in Supabase PostgreSQL

## Deployment

### 1. Prerequisites
- Vercel account (free tier)
- Supabase project (free tier)
- Telegram bot token (from @BotFather)

### 2. Setup Supabase
Run these SQL migrations in your Supabase SQL Editor:

```sql
-- Create the telegram_order_status table
CREATE TABLE IF NOT EXISTS telegram_order_status (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID REFERENCES orders(id) ON DELETE CASCADE NOT NULL UNIQUE,
    current_status TEXT NOT NULL DEFAULT 'New',
    last_transition_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_checked_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Add trigger for timestamp updates
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_telegram_order_status_updated_at
    BEFORE UPDATE ON telegram_order_status
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- Enable RLS and allow anonymous access
ALTER TABLE telegram_order_status ENABLE ROW LEVEL SECURITY;
CREATE POLICY "anon_all_telegram_order_status" ON telegram_order_status FOR ALL USING (true);

-- Create transition function
CREATE OR REPLACE FUNCTION transition_order_status(
    p_order_id UUID,
    p_new_status TEXT
) RETURNS VOID AS $$
DECLARE
    v_current TEXT;
    v_valid_transition BOOLEAN := FALSE;
BEGIN
    SELECT current_status INTO v_current FROM telegram_order_status WHERE order_id = p_order_id;

    IF v_current = 'New' AND p_new_status = 'Prep' THEN
        v_valid_transition := TRUE;
    ELSIF v_current = 'Prep' AND p_new_status = 'Out' THEN
        v_valid_transition := TRUE;
    ELSIF v_current = 'Out' AND p_new_status = 'Done' THEN
        v_valid_transition := TRUE;
    ELSIF p_new_status = 'Done' AND v_current IS NULL THEN
        v_valid_transition := TRUE;
    END IF;

    IF v_valid_transition THEN
        UPDATE telegram_order_status SET
            current_status = p_new_status,
            last_transition_at = NOW(),
            last_checked_by = current_user
        WHERE order_id = p_order_id;
    ELSE
        RAISE EXCEPTION 'Invalid transition from % to %', v_current, p_new_status;
    END IF;
END;
$$ LANGUAGE plpgsql;

GRANT ALL ON telegram_order_status TO anon;
GRANT EXECUTE ON FUNCTION transition_order_status TO anon;
```

### 3. Deploy to Vercel

#### Option A: Via Vercel Dashboard (click-by-click)
1. Go to https://vercel.com/new
2. Import your Git repository or upload files
3. Set environment variables:
   - `TELEGRAM_BOT_TOKEN`: `8935028631:AAFPDx1DzJmbfQg-_J44dyKgxE7XrYdEaaY`
   - `ORDER_GROUP`: `@f2d_order`
   - `SUPABASE_URL`: `https://gzzlokhsibryyflddikh.supabase.co`
   - `SUPABASE_ANON_KEY`: Your Supabase anon/public key
4. Deploy!

#### Option B: Via CLI
```bash
cd /Users/anwarhusaini/food2door-telegram-bot
vercel
```

### 4. Bot Commands

#### `/start` - Create new order
Sends a new order with "New" status and "Start Prep" button.

#### `/status` - Check active orders
Shows orders that aren't marked as Done.

### 5. How the Workflow Works

1. **Atan/Bella keys in order** → Clicks `/start` or bot receives order
2. Bot creates order with status: **New**
3. Keyboard shows: [`Start Prep`]
4. Atan/Bella clicks **Start Prep** → Status becomes **Prep**
5. Keyboard shows: [`Mark Out`]
6. Cook staff marks as **Out** (in different group)
7. Atan/Bella clicks **Mark Out** → Status becomes **Out**
8. Keyboard shows: [`Mark Done`]
9. Cook staff marks as **Done** after delivery
10. Atan/Bella clicks **Mark Done** → Status becomes **Done** ✅

### 6. Cron Reminders
The bot includes a cron job that runs every 2 minutes and checks for orders stuck in New/Prep/Out status for over 10 minutes. It sends a reminder to `@f2d_order` group.

### 7. Environment Variables
Create a `.env` file or set in Vercel dashboard:

```
TELEGRAM_BOT_TOKEN=8935028631:AAFPDx1DzJmbfQg-_J44dyKgxE7XrYdEaaY
ORDER_GROUP=@f2d_order
SUPABASE_URL=https://gzzlokhsibryyflddikh.supabase.co
SUPABASE_ANON_KEY=YOUR_SUPABASE_ANON_KEY_HERE
FOOD2DOOR_DB=/path/to/food2door.db (optional, for SQLite fallback)
```

### 8. File Structure
```
/food2door-telegram-bot/
├── bot.py           # Main bot application
├── cron_reminder.py # 10-minute reminder cron job
├── vercel.json      # Vercel deployment config
├── .env.example     # Environment variable examples
└── package.json     # Dependencies (if needed)
```

## Dependencies
The bot requires:
- `python-telegram-bot` or `aiogram` for Telegram API
- `supabase` Python SDK for database connectivity
- Standard library: `sqlite3`, `os`, `datetime`

## Notes
- The bot uses Supabase PostgreSQL for persistent state tracking
- SQLite is used as a local fallback/cache
- All status transitions are validated to prevent invalid state changes
- The 10-minute cron reminder helps keep the workflow moving
