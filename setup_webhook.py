#!/usr/bin/env python3
"""Script for setting up Telegram bot webhook."""
import sys
import requests
import os

TOKEN = "8712544685:AAFSBxPDOrY1G7hEjbigVB3rNRp3t3Y8e5E"

def set_webhook(url):
    webhook_url = f"{url.rstrip('/')}/webhook/{TOKEN}"
    print(f"Setting webhook to: {webhook_url}")
    resp = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/setWebhook",
        json={"url": webhook_url},
        timeout=10
    )
    result = resp.json()
    if result.get("ok"):
        print(f"OK! Webhook set: {webhook_url}")
    else:
        print(f"Failed: {result}")
    return result

def get_webhook_info():
    resp = requests.get(f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo", timeout=10)
    return resp.json()

def delete_webhook():
    resp = requests.post(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook", timeout=10)
    return resp.json()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        set_webhook(sys.argv[1])
    else:
        info = get_webhook_info()
        print("Current webhook info:")
        import json
        print(json.dumps(info, indent=2))
