import os
import sys
import json
import logging
import traceback
from pathlib import Path



logger = logging.getLogger(__name__)

# ============================================================
# InterpreterHandler - مديريت LLM با قابليت جستجوي اينترنت
# ============================================================

class InterpreterHandler:

    def __init__(self):
        self.workspace_base = Path(os.getenv("WORKSPACE_DIR", "/app/workspace"))
        self.sessions_dir = Path(os.getenv("SESSIONS_DIR", "/app/sessions"))
        self.workspace_base.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.max_history = int(os.getenv("MAX_HISTORY", 50))
        self.llm_api_key = os.getenv("LLM_API_KEY") or os.getenv("INTERPRETER_API_KEY")
        self.llm_base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
        self.llm_model = os.getenv("LLM_MODEL", "deepseek-chat")

    async def process_message(self, chat_id: int, message: str) -> str:
        try:
            return await self._call_llm(chat_id, message)
        except Exception as e:
            logger.error(f"LLM error: {e}", exc_info=True)
            return f"⚠️ **خطا در پردازش درخواست**\n\n❌ {str(e)[:200]}"

    async def _web_search(self, query: str, max_results: int = 5) -> str:
        try:
            import requests as req
            from urllib.parse import quote
            
            resp = req.get(
                "https://lite.duckduckgo.com/lite/",
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=15
            )
            if resp.status_code != 200:
                return ""
            
            import re
            # Extract results from DuckDuckGo lite HTML
            results = []
            # Find all result links and snippets
            links = re.findall(r'<a[^>]*class="result-link"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>', resp.text)
            snippets = re.findall(r'<td class="result-snippet">(.*?)</td>', resp.text, re.DOTALL)
            
            for i, (href, title) in enumerate(links[:max_results]):
                snippet = snippets[i] if i < len(snippets) else ""
                snippet = re.sub(r"<[^>]+>", "", snippet).strip()[:200]
                title = re.sub(r"<[^>]+>", "", title).strip()
                results.append(f"{i+1}. {title}   {snippet}   Source: {href}")
            
            return "\n".join(results) if results else ""
        except Exception as e:
            logger.error(f"Web search error: {e}")
            return ""

    async def _call_llm(self, chat_id: int, message: str) -> str:
        import aiohttp
        api_key = self.llm_api_key
        if not api_key:
            return self._offline_message()

        history = self._load_history(chat_id)
        messages = history + [{"role": "user", "content": message}]

        # Check if the query needs web search
        search_keywords = ["خبر", "news", "اخبار", "آخرین", "latest", "جستجو", "search", "this week", "today", "امروز", "now", "الان", "current", "newest"]
        needs_search = any(kw in message.lower() for kw in search_keywords)
        search_context = ""
        if needs_search:
            search_context = await self._web_search(message)

        system_prompt = (
            "You are a helpful AI assistant running on a Telegram bot. "
            "Respond in Persian (Farsi) unless the user writes in another language. "
            "Be concise, friendly, and helpful. "
            "You can answer questions, explain concepts, write code, analyze data, and search the web. "
            "Keep responses reasonably short for a chat environment."
        )

        url = f"{self.llm_base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        api_messages = [{"role": "system", "content": system_prompt}]
        if search_context:
            search_msg = {
                "role": "system",
                "content": f"Web search results for user query:\n\n{search_context}\n\nUse these results to answer the user if relevant."
            }
            api_messages.append(search_msg)
        api_messages += messages

        payload = {
            "model": self.llm_model,
            "messages": api_messages,
            "max_tokens": 2048,
            "temperature": 0.7
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                    data = await resp.json()
                    if resp.status != 200:
                        error_msg = data.get("error", {}).get("message", str(data))
                        logger.error(f"API error {resp.status}: {error_msg}")
                        return f"⚠️ خطا در ارتباط با سرویس: {error_msg[:150]}"
                    if "choices" in data and len(data["choices"]) > 0:
                        reply = data["choices"][0]["message"]["content"]
                        updated = messages + [{"role": "assistant", "content": reply}]
                        self._save_history(chat_id, updated)
                        return reply
                    else:
                        return "⚠️ پاسخ غیرمنتظره از سرور."
        except asyncio.TimeoutError:
            return "⏱️ زمان درخواست به پایان رسید."
        except aiohttp.ClientError as e:
            return f"🔐 خطای ارتباط: {str(e)[:100]}"

    def _offline_message(self) -> str:
        return (
            "⚠️ **حالت آفلاین**\n\n"
            "برای استفاده از ربات، LLM_API_KEY را در Railway Variables ست کنید."
        )

    def _load_history(self, chat_id: int) -> list:
        history_file = self.sessions_dir / f"{chat_id}.json"
        if history_file.exists():
            try:
                with open(history_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                return []
        return []

    def _save_history(self, chat_id: int, messages: list):
        history_file = self.sessions_dir / f"{chat_id}.json"
        if len(messages) > self.max_history:
            messages = messages[-self.max_history:]
        try:
            with open(history_file, "w", encoding="utf-8") as f:
                json.dump(messages, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error saving history: {e}")
