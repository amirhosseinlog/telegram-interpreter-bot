import os
import json
import logging
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

class SessionManager:
    """
    مدیریت session کاربران
    - ذخیره و بازیابی تاریخچه مکالمات
    - پشتیبانی از expiration
    - مدیریت فایل‌های موقت
    """
    
    def __init__(self, sessions_dir: str = None, ttl_seconds: int = 86400):
        """
        Args:
            sessions_dir: مسیر پوشه ذخیره session
            ttl_seconds: زمان انقضای پیش‌فرض (ثانیه) - 24 ساعت
        """
        self.sessions_dir = Path(sessions_dir or os.getenv('SESSIONS_DIR', '/app/sessions'))
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl_seconds
        
        # پوشه فایل‌های موقت کاربران
        self.files_dir = self.sessions_dir.parent / 'user_files'
        self.files_dir.mkdir(parents=True, exist_ok=True)
    
    def get_history(self, chat_id: int) -> List[Dict[str, str]]:
        """دریافت تاریخچه مکالمه کاربر"""
        filepath = self._get_history_path(chat_id)
        if not filepath.exists():
            return []
        
        try:
            # بررسی expiration
            if self._is_expired(filepath):
                self.clear_history(chat_id)
                return []
            
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get('messages', [])
        except Exception as e:
            logger.error(f'Error loading history for {chat_id}: {e}')
            return []
    
    def save_message(self, chat_id: int, role: str, content: str, max_history: int = 50):
        """ذخیره یک پیام در تاریخچه"""
        history = self.get_history(chat_id)
        
        history.append({
            'role': role,
            'content': content,
            'timestamp': int(time.time())
        })
        
        # محدود کردن تعداد پیام‌ها
        if len(history) > max_history:
            history = history[-max_history:]
        
        self._save_history(chat_id, history)
    
    def save_conversation(self, chat_id: int, messages: List[Dict[str, str]], max_history: int = 50):
        """ذخیره کل مکالمه"""
        if len(messages) > max_history:
            messages = messages[-max_history:]
        self._save_history(chat_id, messages)
    
    def _save_history(self, chat_id: int, messages: List[Dict[str, str]]):
        """ذخیره تاریخچه روی دیسک"""
        filepath = self._get_history_path(chat_id)
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump({
                    'chat_id': chat_id,
                    'updated_at': int(time.time()),
                    'expires_at': int(time.time()) + self.ttl,
                    'messages': messages
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f'Error saving history for {chat_id}: {e}')
    
    def clear_history(self, chat_id: int):
        """پاک کردن تاریخچه کاربر"""
        filepath = self._get_history_path(chat_id)
        try:
            if filepath.exists():
                filepath.unlink()
                logger.info(f'Cleared history for {chat_id}')
        except Exception as e:
            logger.error(f'Error clearing history for {chat_id}: {e}')
    
    def get_user_files(self, chat_id: int) -> List[Path]:
        """لیست فایل‌های کاربر"""
        user_dir = self.files_dir / str(chat_id)
        if not user_dir.exists():
            return []
        return list(user_dir.iterdir())
    
    def save_user_file(self, chat_id: int, filename: str, content: bytes) -> Path:
        """ذخیره فایل برای کاربر"""
        user_dir = self.files_dir / str(chat_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        
        filepath = user_dir / filename
        with open(filepath, 'wb') as f:
            f.write(content)
        
        return filepath
    
    def get_stats(self) -> Dict[str, Any]:
        """آمار session‌ها"""
        sessions = list(self.sessions_dir.glob('*.json'))
        active = 0
        total_messages = 0
        
        for s in sessions:
            try:
                with open(s, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if not self._is_expired(s):
                    active += 1
                    total_messages += len(data.get('messages', []))
            except:
                pass
        
        return {
            'total_sessions': len(sessions),
            'active_sessions': active,
            'total_messages': total_messages,
            'sessions_dir': str(self.sessions_dir),
            'ttl_seconds': self.ttl
        }
    
    def cleanup_expired(self):
        """پاکسازی session‌های منقضی شده"""
        cleaned = 0
        for s in self.sessions_dir.glob('*.json'):
            if self._is_expired(s):
                try:
                    s.unlink()
                    cleaned += 1
                except:
                    pass
        
        if cleaned:
            logger.info(f'Cleaned up {cleaned} expired sessions')
        return cleaned
    
    def _get_history_path(self, chat_id: int) -> Path:
        return self.sessions_dir / f'{chat_id}.json'
    
    def _is_expired(self, filepath: Path) -> bool:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            expires = data.get('expires_at', 0)
            return time.time() > expires
        except:
            return False
