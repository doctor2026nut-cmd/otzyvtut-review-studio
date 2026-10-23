"""Универсальный клиент для генерации текстов и рерайта.
По умолчанию использует OpenAI-совместимый API:
API Base: https://agent-master-server.onrender.com/v1
Model: antigravity-3.8-pro
Key: sk-antigravity-master-roman
Поддерживает fallback на Google Gemini API при необходимости.
"""
import os, json, re, requests

DEFAULT_API_BASE = "https://agent-master-server.onrender.com/v1"
DEFAULT_API_KEY = "sk-antigravity-master-roman"
DEFAULT_MODEL = "antigravity-3.8-pro"

def call_llm(prompt, system_instruction=None, temperature=0.7, max_tokens=1000):
    """Вызов нейросети через Agent-Master OpenAI-compatible endpoint."""
    url = f"{DEFAULT_API_BASE.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEFAULT_API_KEY}",
        "Content-Type": "application/json"
    }

    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": DEFAULT_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"LLM API returned {r.status_code}: {r.text[:300]}")
        data = r.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        raise RuntimeError(f"Ошибка обращения к LLM ({DEFAULT_MODEL}): {e}")
