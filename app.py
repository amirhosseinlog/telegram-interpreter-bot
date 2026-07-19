import os
import sys
import json
import logging
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if not TOKEN:
    logger.error('TELEGRAM_BOT_TOKEN not set!')
    sys.exit(1)

API = f'https://api.telegram.org/bot{TOKEN}'


def send_message(chat_id, text):
    try:
        requests.post(f'{API}/sendMessage', json={'chat_id': chat_id, 'text': text}, timeout=10)
    except Exception as e:
        logger.error(f'Send error: {e}')


def send_typing(chat_id):
    try:
        requests.post(f'{API}/sendChatAction', json={'chat_id': chat_id, 'action': 'typing'}, timeout=3)
    except:
        pass


@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()
    if not update:
        return jsonify({'ok': False}), 400

    msg = update.get('message', {})
    chat_id = msg.get('chat', {}).get('id')
    text = msg.get('text', '')

    if not chat_id or not text:
        return jsonify({'ok': True})

    logger.info(f'[{chat_id}] {text[:60]}')
    send_typing(chat_id)

    from interpreter_handler import InterpreterHandler
    handler = InterpreterHandler()
    response = handler.process_message(chat_id, text)

    if response:
        if len(response) > 4000:
            for i in range(0, len(response), 4000):
                send_message(chat_id, response[i:i+4000])
        else:
            send_message(chat_id, response)

    return jsonify({'ok': True})


@app.route('/webhook/' + TOKEN, methods=['POST'])
def webhook_token():
    return webhook()


@app.route('/')
def home():
    return '<h1>Bot Running</h1>'


@app.route('/health')
def health():
    from interpreter_handler import InterpreterHandler
    h = InterpreterHandler()
    return jsonify({'status': 'ok', 'model': h.llm_model, 'base_url': h.llm_base_url, 'has_key': bool(h.llm_api_key)})


@app.route('/debug')
def debug():
    from interpreter_handler import InterpreterHandler
    h = InterpreterHandler()
    return jsonify({
        'model': h.llm_model,
        'base_url': h.llm_base_url,
        'has_key': bool(h.llm_api_key),
        'env_model': os.getenv('LLM_MODEL', 'NOT SET'),
        'env_url': os.getenv('LLM_BASE_URL', 'NOT SET')
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    logger.info(f'Starting on port {port}')
    app.run(host='0.0.0.0', port=port, debug=False)
