
import os
import json
import logging
import requests
import threading
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
            return "\u26a0\ufe0f \u062e\u0637\u0627: " + str(e)[:200]

    def _web_search(self, query):
        """Real web search via duckduckgo_search - runs in thread with timeout"""
        result = []

        def _do_search():
            try:
                from duckduckgo_search import DDGS
                ddgs = DDGS()
                results = list(ddgs.text(query, max_results=5))
                for i, r in enumerate(results, 1):
                    title = r.get("title", "")
                    body = r.get("body", "")
                    href = r.get("href", "")
                    result.append(f"{i}. {title}\n   {body}\n   {href}")
            except Exception as e:
                result.append("ERROR: " + str(e))

        t = threading.Thread(target=_do_search, daemon=True)
        t.start()
        t.join(timeout=6)

        if t.is_alive():
            return ""  # timeout, return empty
        return "\n".join(result) if result else ""

    def _call_llm(self, chat_id, message):
        if not self.llm_api_key:
            return "\u26a0\ufe0f \u062d\u0627\u0644\u062a \u0622\u0641\u0644\u0627\u06cc\u0646"

        history = self._load_history(chat_id)

        # Web search trigger keywords
        search_kw = [
            "\u0627\u062e\u0628\u0627\u0631", "news", "\u062e\u0628\u0631", "\u0622\u062e\u0631\u06cc\u0646", "latest",
            "\u0627\u0645\u0631\u0648\u0632", "today", "\u0627\u0644\u0627\u0646", "now", "current",
            "\u0642\u06cc\u0645\u062a", "price", "\u0646\u0631\u062e", "rate", "\u062f\u0644\u0627\u0631", "dollar",
            "\u06cc\u0648\u0631\u0648", "euro", "\u0628\u06cc\u062a\u06a9\u0648\u06cc\u0646", "bitcoin",
            "\u0633\u0647\u0627\u0645", "stock", "\u0628\u0648\u0631\u0633", "market",
            "\u0647\u0648\u0627", "weather", "\u0622\u0628\u0648\u0647\u0648\u0627",
            "\u062c\u0633\u062a\u062c\u0648", "search", "\u0633\u0631\u0686", "google",
            "\u0646\u062a\u0627\u06cc\u062c", "result", "\u0645\u0642\u0627\u0644\u0647", "article",
        ]
        msg_lower = message.lower()
        needs_search = any(kw in msg_lower for kw in search_kw)

        search_text = ""
        if needs_search:
            search_text = self._web_search(message)

        # System prompt
        if search_text:
            system_prompt = (
                "You are a helpful AI assistant. Always respond in Persian (Farsi) unless asked otherwise. "
                "You have access to live web search results shown below. "
                "Use them to answer precisely. Always cite the source URL.\n\n"
                "WEB SEARCH RESULTS:\n" + search_text + "\n\n"
                "IMPORTANT: Use these search results NOW. If they are empty, say the search failed."
            )
        else:
            system_prompt = (
                "You are a helpful AI assistant. "
                "Always respond in Persian (Farsi) unless asked otherwise. "
                "Be concise and direct. Keep responses short for Telegram chat."
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
                logger.error(f"API error {resp.status_code}: {error_msg}")
                return "\u26a0\ufe0f \u062e\u0637\u0627: " + error_msg[:150]

            if "choices" in data and len(data["choices"]) > 0:
                reply = data["choices"][0]["message"]["content"]
                self._save_history(chat_id, messages[1:] + [{"role": "assistant", "content": reply}])
                return reply

            return "\u26a0\ufe0f \u067e\u0627\u0633\u062e \u063a\u06cc\u0631\u0645\u0646\u062a\u0638\u0631\u0647"

        except requests.Timeout:
            return "\u23f1\ufe0f \u0632\u0645\u0627\u0646 \u067e\u0627\u0633\u062e \u0637\u0648\u0644\u0627\u0646\u06cc"
        except Exception as e:
            logger.error(f"HTTP error: {e}")
            return "\ud83d\udd0c \u062e\u0637\u0627\u06cc \u0627\u0631\u062a\u0628\u0627\u0637: " + str(e)[:100]

    def _offline_message(self):
        return "\u26a0\ufe0f \u062d\u0627\u0644\u062a \u0622\u0641\u0644\u0627\u06cc\u0646. LLM_API_KEY \u062a\u0646\u0638\u06cc\u0645 \u0646\u0634\u062f\u0647."

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

