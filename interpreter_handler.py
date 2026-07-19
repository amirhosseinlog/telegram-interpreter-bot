import os
import json
import logging
import requests
import re
import threading
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

class InterpreterHandler:
    def __init__(self):
        self.workspace_base = Path(os.getenv("WORKSPACE_DIR", "/app/workspace"))
        self.sessions_dir = Path(os.getenv("SESSIONS_DIR", "/app/sessions"))
        self.workspace_base.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.max_history = 6

        self.llm_api_key = os.getenv("LLM_API_KEY") or os.getenv("INTERPRETER_API_KEY") or "[REDACTED]"
        self.llm_base_url = "https://router.bynara.id/v1"
        self.llm_model = "deepseek-v4-pro-bynara"

    def process_message(self, chat_id, message):
        try:
            return self._call_llm(chat_id, message)
        except Exception as e:
            logger.error(f"LLM error: {e}", exc_info=True)
            return "[ERROR] " + str(e)[:200]

    def _web_search(self, query):
        """Fast web search via DuckDuckGo HTML"""
        result = []

        def _do_search():
            try:
                today = datetime.now()
                search_query = f"{query} {today.year}"

                r = requests.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": search_query},
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=5
                )
                if r.status_code != 200:
                    return

                html = r.text
                blocks = re.findall(r'<a rel="nofollow" class="result__a" href="(.*?)">(.*?)</a>', html, re.DOTALL)
                snippets = re.findall(r'<a class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)

                for i, (url, title) in enumerate(blocks[:3]):
                    title_clean = re.sub(r'<[^>]+>', '', title).strip()
                    snippet_clean = ""
                    if i < len(snippets):
                        snippet_clean = re.sub(r'<[^>]+>', '', snippets[i]).strip()
                    result.append(f"{i+1}. {title_clean}")
                    if snippet_clean:
                        result.append(f"   {snippet_clean}")
                    result.append(f"   {url}")

            except Exception as e:
                logger.error(f"Search error: {e}")

        t = threading.Thread(target=_do_search, daemon=True)
        t.start()
        t.join(timeout=5)

        return "\n".join(result) if result else ""

    def _call_llm(self, chat_id, message):
        if not self.llm_api_key:
            return "[OFFLINE]"

        history = self._load_history(chat_id)
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")

        # Trigger search only for explicit news/price queries
        search_kw = ["news", "price", "rate", "weather", "stock", "market"]
        msg_lower = message.lower()
        needs_search = any(kw in msg_lower for kw in search_kw) and len(message) > 5

        search_text = ""
        if needs_search:
            search_text = self._web_search(message)

        if search_text and len(search_text) > 20:
            system_prompt = (
                f"Today is {today_str}. You are a helpful assistant. "
                "Always respond in Persian (Farsi). "
                "Use these web search results to answer:\n\n" + search_text
            )
        else:
            system_prompt = (
                f"Today is {today_str}. "
                "You are a helpful assistant. Always respond in Persian (Farsi). Be concise."
            )

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history[-6:])
        messages.append({"role": "user", "content": message})

        try:
            resp = requests.post(
                f"{self.llm_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.llm_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.llm_model,
                    "messages": messages,
                    "max_tokens": 800,
                    "temperature": 0.7
                },
                timeout=20
            )
            data = resp.json()

            if resp.status_code != 200:
                return "[ERROR] " + data.get("error", {}).get("message", str(data))[:150]

            if "choices" in data and len(data["choices"]) > 0:
                reply = data["choices"][0]["message"]["content"]
                self._save_history(chat_id, messages[1:] + [{"role": "assistant", "content": reply}])
                return reply

            return "[ERROR] Unexpected"

        except requests.Timeout:
            return "[TIMEOUT] Try again"
        except Exception as e:
            return "[ERROR] " + str(e)[:100]

    def _load_history(self, chat_id):
        history_file = self.sessions_dir / f"{chat_id}.json"
        if history_file.exists():
            try:
                with open(history_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                return []
        return []

    def _save_history(self, chat_id, messages):
        history_file = self.sessions_dir / f"{chat_id}.json"
        if len(messages) > self.max_history:
            messages = messages[-self.max_history:]
        try:
            with open(history_file, "w", encoding="utf-8") as f:
                json.dump(messages, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error saving history: {e}")