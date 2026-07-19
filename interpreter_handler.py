import os
import sys
import json
import logging
import traceback
import asyncio
from pathlib import Path

logger = logging.getLogger(__name__)

# ============================================================
# InterpreterHandler - مدیریت Interpreter و اجرای کد
# ============================================================

class InterpreterHandler:
    """
    مدیریت ارتباط با LLM از طریق OpenAI-compatible API
    - هر کاربر یک session جداگانه داره
    - پشتیبانی از DeepSeek، OpenAI و سایر providerهای سازگار
    - مدیریت فایلها و امنیت
    """

    def __init__(self):
        self.workspace_base = Path(os.getenv('WORKSPACE_DIR', '/app/workspace'))
        self.sessions_dir = Path(os.getenv('SESSIONS_DIR', '/app/sessions'))

        self.workspace_base.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        self.max_history = int(os.getenv('MAX_HISTORY', 50))

        # LLM settings - OpenAI-compatible (works with DeepSeek, OpenAI, etc.)
        self.llm_api_key = os.getenv('LLM_API_KEY') or os.getenv('INTERPRETER_API_KEY')
        self.llm_base_url = os.getenv('LLM_BASE_URL', 'https://api.deepseek.com').rstrip('/')
        self.llm_model = os.getenv('LLM_MODEL', 'deepseek-chat')

    async def process_message(self, chat_id: int, message: str) -> str:
        """
        پردازش پیام کاربر با LLM

        Args:
            chat_id: آیدی عددی چت
            message: متن پیام کاربر

        Returns:
            str: پاسخ تولید شده
        """
        try:
            return await self._call_llm(chat_id, message)
        except Exception as e:
            logger.error(f'LLM error: {e}', exc_info=True)
            return (
                '⚠️ **خطا در پردازش درخواست**\n\n'
                f'❌ {str(e)[:200]}'
            )

    async def _web_search(self, query: str, max_results: int = 5) -> str:
        """Search the web using DuckDuckGo and return formatted results."""
        try:
            from duckduckgo_search import DDGS
            results = DDGS().text(query, max_results=max_results)
            if not results:
                return ""
            lines = []
            for i, r in enumerate(results, 1):
                title = r.get("title", "")
                body = r.get("body", "")
                href = r.get("href", "")
                lines.append(f"{i}. {title}\n   {body}\n   Source: {href}")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"Web search error: {e}")
            return ""

    async def _call_llm(self, chat_id: int, message: str) -> str:
        """تماس با OpenAI-compatible API"""
        import aiohttp

        api_key = self.llm_api_key
        if not api_key:
            logger.warning('No LLM_API_KEY set, returning offline message')
            return self._offline_message()

        history = self._load_history(chat_id)
        messages = history + [{'role': 'user', 'content': message}]

        # Check if user needs web search
        search_keywords = [
            "خبر", "news", "اخبار", "آخرین", "latest", "جستجو",
            "search", "this week", "today", "امروز", "now", "الان",
            "current", "newest", "هوا", "weather", "قیمت", "price",
            "rate", "نرخ", "دلار", "یورو", "بیتکوین", "bitcoin",
            "سهام", "stock", "بورس", "market"
        ]
        needs_search = any(kw in message.lower() for kw in search_keywords)
        search_context = ""
        if needs_search:
            search_context = await self._web_search(message)

        system_prompt = (
            "You are a helpful AI assistant running on a Telegram bot. "
            "Respond in Persian (Farsi) unless the user writes in another language. "
            "Be concise, friendly, and helpful. "
            "You can: answer questions, explain concepts, write code, analyze data. "
            "Keep responses reasonably short for a chat environment."
        )

        # Build API messages
        if search_context:
            search_msg = {
                "role": "system",
                "content": (
                    f"Web search results for user query:\n\n"
                    f"{search_context}\n\n"
                    f"Use these results to answer the user if relevant. "
                    f"Cite sources when using search results."
                )
            }
            api_messages = [{"role": "system", "content": system_prompt}, search_msg] + messages
        else:
            api_messages = [{"role": "system", "content": system_prompt}] + messages

        url = f'{self.llm_base_url.rstrip("/")}/chat/completions'
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        payload = {
            'model': self.llm_model,
            'messages': api_messages,
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
                        return f'⚠️ خطا در ارتباط با سرویس: {error_msg[:150]}'

                    if 'choices' in data and len(data['choices']) > 0:
                        reply = data['choices'][0]['message']['content']

                        # ذخیره تاریخچه
                        updated = messages + [{'role': 'assistant', 'content': reply}]
                        self._save_history(chat_id, updated)

                        return reply
                    else:
                        logger.error(f'Unexpected API response: {data}')
                        return '⚠️ پاسخ غیرمنتظره از سرور. لطفاً دوباره تلاش کنید.'

        except asyncio.TimeoutError:
            logger.error('API request timed out')
            return '⏱️ زمان درخواست به پایان رسید. لطفاً دوباره تلاش کنید.'
        except aiohttp.ClientError as e:
            logger.error(f'HTTP client error: {e}')
            return f'🔌 خطای ارتباط: {str(e)[:100]}'

    def _offline_message(self) -> str:
        """پیشنمایش آفلاین وقتی API key تنظیم نشده"""
        return (
            '⚠️ **حالت آفلاین**\n\n'
            'برای استفاده از ربات، لطفاً **LLM_API_KEY** رو در محیط ست کنید.\n\n'
            '📌 **روش ست کردن:**\n'
            'در Railway -> Variables -> اضافه کردن:\n'
            '• `LLM_API_KEY` = کلید API (DeepSeek / OpenAI / ...)\n'
            '• `LLM_BASE_URL` = (اختیاری) آدرس سرور\n'
            '• `LLM_MODEL` = (اختیاری) نام مدل\n\n'
            'مثال برای DeepSeek:\n'
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
