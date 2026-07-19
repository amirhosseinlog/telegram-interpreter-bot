import os
import sys
import json
import asyncio
import logging
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if not TELEGRAM_TOKEN:
    logger.error('TELEGRAM_BOT_TOKEN not set!')
    sys.exit(1)

TELEGRAM_API_URL = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}'


def send_message(chat_id, text, parse_mode='Markdown'):
    try:
        resp = requests.post(
            f'{TELEGRAM_API_URL}/sendMessage',
            json={'chat_id': chat_id, 'text': text, 'parse_mode': parse_mode},
            timeout=30
        )
        return resp.json()
    except Exception as e:
        logger.error(f'Error sending message: {e}')
        return None


def send_typing_action(chat_id):
    try:
        requests.post(
            f'{TELEGRAM_API_URL}/sendChatAction',
            json={'chat_id': chat_id, 'action': 'typing'},
            timeout=5
        )
    except:
        pass


# ----------------------------------------------------------------
# Safe async runner — works with sync gunicorn workers AND debug mode
# ----------------------------------------------------------------
def run_async(coro):
    """Execute an async coroutine safely, even if there's a running event loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No loop running — normal for gunicorn sync workers
        return asyncio.run(coro)

    # A loop is already running (Flask debug reloader, async worker, etc.)
    # Spin up a fresh loop in a separate thread
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, coro)
        return future.result()

# ----------------------------------------------------------------


@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()
    if not update:
        return jsonify({'ok': False}), 400

    run_async(handle_update(update))
    return jsonify({'ok': True})


@app.route('/webhook/' + TELEGRAM_TOKEN, methods=['POST'])
def webhook_with_token():
    return webhook()


@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'url parameter required'}), 400
    webhook_url = f'{url.rstrip("/")}/webhook/{TELEGRAM_TOKEN}'
    resp = requests.post(
        f'{TELEGRAM_API_URL}/setWebhook',
        json={'url': webhook_url},
        timeout=10
    )
    if resp.json().get('ok'):
        logger.info(f'Webhook set to {webhook_url}')
    return jsonify(resp.json())


@app.route('/')
def home():
    return '<h1>🤖 Telegram Interpreter Bot</h1><p>Bot is running!</p><p>Set webhook: <code>/set_webhook?url=YOUR_RAILWAY_URL</code></p>'


@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'version': '1.0.0', 'platform': 'railway'})


async def handle_update(update):
    try:
        message = update.get('message', {})
        chat_id = message.get('chat', {}).get('id')
        text = message.get('text', '')

        if not chat_id or not text:
            return

        logger.info(f'Message from {chat_id}: {text[:50]}...')
        send_typing_action(chat_id)

        from interpreter_handler import InterpreterHandler
        handler = InterpreterHandler()
        response = await handler.process_message(chat_id, text)

        if response:
            max_len = 4000
            if len(response) > max_len:
                parts = [response[i:i+max_len] for i in range(0, len(response), max_len)]
                for i, part in enumerate(parts):
                    if i == 0:
                        send_message(chat_id, part)
                    else:
                        send_message(chat_id, f'📄 ادامه ({i+1}/{len(parts)}):\\n{part}')
            else:
                send_message(chat_id, response)
        else:
            send_message(chat_id, '⚠️ متأسفانه پاسخی دریافت نشد.')
    except Exception as e:
        logger.error(f'Error handling update: {e}', exc_info=True)
        try:
            send_message(chat_id, f'❌ خطا: {str(e)[:200]}')
        except:
            pass


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    logger.info(f'Starting server on port {port}')
    app.run(host='0.0.0.0', port=port, debug=False)
