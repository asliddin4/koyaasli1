# RENDER.COM DEPLOY FILES

## Core Bot Files
- `main.py` - Bot entry point
- `config.py` - Configuration and environment variables
- `database.py` - Database operations and schema
- `keyboards.py` - Telegram keyboard layouts
- `messages.py` - Message templates

## Handlers (Bot Logic)
- `handlers/__init__.py`
- `handlers/start.py` - Main menu and user registration
- `handlers/admin.py` - Admin panel and management
- `handlers/content.py` - Content management system
- `handlers/sections.py` - Section and subsection management
- `handlers/tests.py` - Quiz and test system
- `handlers/ai_conversation.py` - AI chat functionality

## Utilities
- `utils/__init__.py`
- `utils/rating_system.py` - User rating and progress tracking
- `utils/scheduler.py` - Automated messaging system
- `utils/subscription_check.py` - Channel subscription verification
- `utils/ai_conversation_advanced.py` - Advanced AI conversation with 12K vocabulary

## Deploy Configuration
- `requirements.txt` - Python dependencies
- `Procfile` - Render startup command
- `render.yaml` - Render.com configuration
- `.gitignore` - Git ignore patterns
- `README.md` - Project documentation

## Total: 21 Files Ready for Deploy

### Environment Variables Needed:
- `BOT_TOKEN` - Your Telegram bot token from @BotFather

### Deploy Command:
```bash
git add .
git commit -m "Korean Language Bot - Deploy Ready"
git push origin main
```