"""
AIRA AI Service - Groq API integration
Handles text chat, PDF analysis, image understanding
"""
import json
import logging
import urllib.request
import urllib.error
from django.conf import settings

logger = logging.getLogger(__name__)

AIRA_SYSTEM_PROMPT = """You are AIRA, a smart helpful AI assistant like ChatGPT.

RESPONSE RULES:
- For simple greetings reply in 1-2 lines only, naturally and friendly
- For simple questions give short direct answers
- For coding questions give clean code with brief explanation
- For complex questions give detailed structured answer
- NEVER give bullet point menus for simple greetings
- Sound natural and human, not like a robot reading a menu
- Use emojis occasionally like ChatGPT does
- Match response length to question complexity

CALCULATOR RULES - when you receive CALCULATOR RESULT in context:
- Show the calculation clearly like: 25 × 48 = **1200**
- If multiple calculations, show each one on a new line
- Show a Final Results summary at the end
- Use bold for the answers
- Be clean and visual like ChatGPT calculator tool

WEATHER RULES - when you receive WEATHER DATA in context:
- Show weather in a clean formatted way with emojis
- Temperature, condition, humidity, wind on separate lines

PYTHON RULES - when you receive PYTHON EXECUTION RESULT:
- Show the output clearly
- If there's an error explain what went wrong
"""
PDF_SYSTEM_PROMPT = """You are AIRA, an expert assistant who helps users understand documents.

When a user uploads a PDF or document:
- Read the ENTIRE document content carefully
- Respond NATURALLY based on what the user asks
- If user says "explain this" then explain everything in simple language
- If user asks a specific question then answer only that question
- If user says "summarize" then give a concise summary
- Match your response style to the document type

NEVER force a fixed structure unless the user asks for it.
Just respond like a smart human expert would - naturally and helpfully.
"""

IMAGE_SYSTEM_PROMPT = """You are AIRA, an expert assistant who helps users understand images.

When a user uploads an image:
- Look at EVERYTHING in the image carefully
- Respond NATURALLY based on what the user asks
- If user says "explain this" then describe and explain everything you see
- If user asks a specific question then answer only that
- Match your response to what the image contains

NEVER force a fixed structure unless the user asks for it.
Just respond like a smart human expert would - naturally, clearly, helpfully.
"""


def get_ai_response(
    messages,
    image_base64=None,
    image_mime=None,
    mode='chat',
    ocr_text=None,
    personalization=None,
    rag_context=None,
):
    api_key = getattr(settings, 'GROQ_API_KEY', None)
    if not api_key:
        return _error("GROQ_API_KEY is not set in .env file")

    if mode == 'pdf':
        system_prompt = PDF_SYSTEM_PROMPT
        model = "llama-3.3-70b-versatile"
    elif mode == 'image':
        system_prompt = IMAGE_SYSTEM_PROMPT
        model = "meta-llama/llama-4-scout-17b-16e-instruct" if image_base64 else "llama-3.3-70b-versatile"
    else:
        system_prompt = AIRA_SYSTEM_PROMPT
        model = "llama-3.3-70b-versatile"

    if personalization:
        system_prompt += "\n\n" + personalization
    if rag_context:
        system_prompt += "\n\n" + rag_context

    chat_messages = [{"role": "system", "content": system_prompt}]

    if ocr_text and mode == 'image':
        chat_messages.append({
            "role": "system",
            "content": "OCR EXTRACTED TEXT:\n" + ocr_text[:3000]
        })

    for i, msg in enumerate(messages):
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == 'system_note':
            continue
        if role not in ("user", "assistant"):
            continue
        is_last_user = (role == "user" and i == len(messages) - 1)
        if image_base64 and is_last_user:
            chat_messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": content},
                    {"type": "image_url", "image_url": {
                        "url": "data:" + image_mime + ";base64," + image_base64
                    }}
                ]
            })
        else:
            chat_messages.append({"role": role, "content": content})

    payload = {
        "model": model,
        "messages": chat_messages,
        "max_tokens": 4096,
        "temperature": 0.6,
    }

    return _call_groq(api_key, payload)


def _call_groq(api_key, payload):
    url = "https://api.groq.com/openai/v1/chat/completions"
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": "Bearer " + api_key,
                "Content-Type": "application/json",
                "User-Agent": "AIRA-Chatbot/2.0",
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))

        if "choices" in result and result["choices"]:
            content = result["choices"][0]["message"]["content"].strip()
            content = content.encode('utf-8').decode('unicode_escape') if '\\u' in content else content
            tokens = result.get("usage", {}).get("total_tokens", 0)
            return {"success": True, "content": content, "tokens": tokens, "error": ""}

        return _error("Unexpected response format from Groq API")

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        if e.code == 401:
            return _error("Invalid Groq API key. Check your .env file.")
        if e.code == 429:
            return _error("Rate limit exceeded. Please wait a moment and try again.")
        if e.code == 413:
            return _error("Request too large. Try a smaller file.")
        try:
            err = json.loads(body)
            msg = err.get("error", {}).get("message", body[:300])
            return _error("Groq API error: " + msg)
        except Exception:
            return _error("HTTP " + str(e.code) + ": " + body[:300])

    except urllib.error.URLError as e:
        return _error("Network error: " + str(e.reason))

    except Exception as e:
        logger.exception("Groq API call failed")
        return _error(str(e))


def _error(msg):
    return {"success": False, "content": "", "tokens": 0, "error": msg}


def generate_title(first_message):
    clean = first_message.replace('📄', '').replace('🖼️', '').replace('📎', '').strip()
    words = clean.split()
    title = " ".join(words[:7])
    return (title + "...") if len(words) > 7 else title or "New Chat"