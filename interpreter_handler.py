import os
import sys
import json
import logging
import traceback
from pathlib import Path

logger = logging.getLogger(__name__)

# ============================================================
# InterpreterHandler - مديريت Interpreter و اجراي كد
# ============================================================

class InterpreterHandler:
    """
    مديريت ارتباط با LLM از طريق OpenAI-compatible API
    - هر كاربر يك session جداگانه داره
    - پشتيباني از DeepSeek، OpenAI و ساير providerهاي سازگار
    - مديريت فايل‌ها و امنيت
    """

    def __init__(self):
        self.workspace_base = Path(os.getenv('WORKSPACE_DIR', '/app/workspace'))
        self.sessions_dir = Path(os.getenv('SESSIONS_DIR', '/app/sessions'))

        self.workspace_base.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        self.max_history = int(os.getenv('MAX_HISTORY', 50))

        # LLM settings — OpenAI-compatible (works with DeepSeek, OpenAI, etc.)
        self.llm_api_key = os.getenv('LLM_API_KEY') or os.getenv('INTERPRETER_API_KEY')
        self.llm_base_url = os.getenv('LLM_BASE_URL', 'https://api.deepseek.com').rstrip('/')
        self.llm_model = os.getenv('LLM_MODEL', 'deepseek-chat')

    async def process_message(self, chat_id: int, message: str) -> str:
        """
        پردازش پيام كاربر با LLM

        Args:
            chat_id: آيدي عددي چت
            message: متن پيام كاربر

        Returns:
            str: پاسخ توليد شده
        """
        try:
            return await self._call_llm(chat_id, message)
        except Exception as e:
            logger.error(f'LLM error: {e}', exc_info=True)
            return (
                '⚠️ **خطا در پردازش درخواست**\n\n'
                f'❌ {str(e)[:200]}'
            )

    async def _call_llm(self, chat_id: int, message: str) -> str:
        """تماس با OpenAI-compatible API"""
        import aiohttp

        api_key = self.llm_api_key
        if not api_key:
            logger.warning('No LLM_API_KEY set, returning offline message')
            return self._offline_message()

        history = self._load_history(chat_id)
        messages = history + [{'role': 'user', 'content': message}]

        system_prompt = (
            'You are a helpful AI assistant running on a Telegram bot. '
            'Respond in Persian (Farsi) unless the user writes in another language. '
            'Be concise, friendly, and helpful. '
            'You can: answer questions, explain concepts, write code, analyze data. '
            'Keep responses reasonably short for a chat environment.'
        )

        url = f'{self.llm_base_url.rstrip("/")}/chat/completions'
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        payload = {
            'model': self.llm_model,
            'messages': [{'role': 'system', 'content': system_prompt}] + messages,
            'max_tokens': 2048,
            'temperature': 0.7
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as resp:
                    data = await resp.json()

                    if resp.status != 200:
                        error_msg = data.get('error', {}).get('message', str(data))
                        logger.error(f'API error {resp.status}: {error_msg}')
                        return f'⚠️ خطا در ارتباط با سرويس: {error_msg[:150]}'

                    if 'choices' in data and len(data['choices']) > 0:
                        reply = data['choices'][0]['message']['content']

                        # ذخيره تاريخچه
                        updated = messages + [{'role': 'assistant', 'content': reply}]
                        self._save_history(chat_id, updated)

                        return reply
                    else:
                        logger.error(f'Unexpected API response: {data}')
                        return '⚠️ پاسخ غيرمنتظره از سرور. لطفاً دوباره تلاش كنيد.'

        except asyncio.TimeoutError:
            logger.error('API request timed out')
            return '⏱️ زمان درخواست به پايان رسيد. لطفاً دوباره تلاش كنيد.'
        except aiohttp.ClientError as e:
            logger.error(f'HTTP client error: {e}')
            return f'🔌 خطاي ارتباط: {str(e)[:100]}'

    def _offline_message(self) -> str:
        """پيش‌نمايش آفلاين وقتي API key تنظيم نشده"""
        return (
            '⚠️ **حالت آفلاين**\n\n'
            'براي استفاده از ربات، لطفاً **LLM_API_KEY** رو در محيط ست كنيد.\n\n'
            '📌 **روش ست كردن:**\n'
            'در Railway -> Variables -> اضافه كردن:\n'
            '• `LLM_API_KEY` = كليد API (DeepSeek / OpenAI / ...)\n'
            '• `LLM_BASE_URL` = (اختياري) آدرس سرور\n'
            '• `LLM_MODEL` = (اختياري) نام مدل\n\n'
            'مثال براي DeepSeek:\n'
            '```\n'
            'LLM_API_KEY=sk-your-key\n'
            'LLM_BASE_URL=https://api.deepseek.com\n'
            'LLM_MODEL=deepseek-chat\n'
            '```'
        )

    def _load_history(self, chat_id: int) -> list:
        history_file = self.sessions_dir / f'{chat_id}.json'
        if history_file.exists():
            try:
                with open(history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return []
        return []

    def _save_history(self, chat_id: int, messages: list):
        history_file = self.sessions_dir / f'{chat_id}.json'
        if len(messages) > self.max_history:
            messages = messages[-self.max_history:]
        try:
            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump(messages, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f'Error saving history: {e}')
