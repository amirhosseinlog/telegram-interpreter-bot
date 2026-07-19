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
        self.max_history = 10

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
        """Web search via DuckDuckGo HTML scraping"""
        result = []

        def _do_search():
            try:
                # Add current year to force fresh results
                today = datetime.now()
                search_query = f"{query} {today.year}"

                r = requests.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": search_query},
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:120.0) Gecko/20100101 Firefox/120.0"},
                    timeout=8
                )
                if r.status_code != 200:
                    result.append("Search failed")
                    return

                html = r.text
                blocks = re.findall(r'<a rel="nofollow" class="result__a" href="(.*?)">(.*?)</a>', html, re.DOTALL)
                snippets = re.findall(r'<a class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)

                for i, (url, title) in enumerate(blocks[:5]):
                    title_clean = re.sub(r'<[^>]+>', '', title).strip()
                    snippet_clean = ""
                    if i < len(snippets):
                        snippet_clean = re.sub(r'<[^>]+>', '', snippets[i]).strip()
                    result.append(f"{i+1}. {title_clean}")
                    if snippet_clean:
                        result.append(f"   {snippet_clean}")
                    result.append(f"   {url}")

                if not result:
                    result.append("No results")

            except Exception as e:
                result.append("Search error: " + str(e))

        t = threading.Thread(target=_do_search, daemon=True)
        t.start()
        t.join(timeout=7)

        if t.is_alive():
            return ""
        return "\n".join(result) if result else ""

    def _call_llm(self, chat_id, message):
        if not self.llm_api_key:
            return "[OFFLINE]"

        history = self._load_history(chat_id)

        # Current date for context
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d (%A)")
        today_persian = f"{now.year}/{now.month:02d}/{now.day:02d}"

        # Web search triggers
        search_kw = [
            "news", "today", "now", "current", "latest", "price", "rate",
            "dollar", "euro", "bitcoin", "stock", "market", "weather",
            "search", "google", "result", "article"
        ]
        msg_lower = message.lower()
        needs_search = any(kw in msg_lower for kw in search_kw)

        search_text = ""
        if needs_search:
            search_text = self._web_search(message)

        if search_text and "No results" not in search_text and "Search error" not in search_text:
            system_prompt = (
                f"You are a helpful AI assistant. TODAY'S DATE IS {today_str}. "
                f"The current year is {now.year}. "
                "Always respond in Persian (Farsi). "
                "You have LIVE web search results below. Use them to answer precisely. "
                "ALWAYS include the date/source of each piece of news. "
                "If results seem old, say so clearly.\n\n"
                "WEB SEARCH RESULTS:\n" + search_text
            )
        else:
            system_prompt = (
                f"You are a helpful AI assistant. TODAY'S DATE IS {today_str}. "
                f"The current year is {now.year}. "
                "Always respond in Persian (Farsi). "
                "Be concise and direct. Keep responses short."
            )

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history[-8:])
        messages.append({"role": "user", "content": message})

        url = f"{self.llm_base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.llm_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.llm_model,
            "messages": messages,
            "max_tokens": 1024,
            "temperature": 0.7
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=25)
            data = resp.json()

            if resp.status_code != 200:
                error_msg = data.get("error", {}).get("message", str(data))
                return "[ERROR] " + error_msg[:150]

            if "choices" in data and len(data["choices"]) > 0:
                reply = data["choices"][0]["message"]["content"]
                self._save_history(chat_id, messages[1:] + [{"role": "assistant", "content": reply}])
                return reply

            return "[ERROR] Unexpected"

        except requests.Timeout:
            return "[TIMEOUT]"
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