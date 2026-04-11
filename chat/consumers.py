
"""
AIRA WebSocket Consumer — Real-time streaming for text messages
"""
import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from groq import Groq
from django.conf import settings
from .models import Conversation, Message

try:
    from .tools import detect_tool_request, run_calculator, get_weather, format_weather, run_python, format_python_result
    TOOLS_OK = True
except Exception:
    TOOLS_OK = False

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
- Show the calculation clearly like: 25 x 48 = 1200
- If multiple calculations, show each one on a new line
- Show a Final Results summary at the end
- Use bold for the answers

WEATHER RULES - when you receive WEATHER DATA in context:
- Show weather in a clean formatted way with emojis
- Temperature, condition, humidity, wind on separate lines

PYTHON RULES - when you receive PYTHON EXECUTION RESULT:
- Show the output clearly
- If there is an error explain what went wrong
"""


class ChatConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        if not self.scope['user'].is_authenticated:
            await self.close()
            return
        self.user = self.scope['user']
        self.conv_id = self.scope['url_route']['kwargs'].get('conv_id')
        await self.accept()

    async def disconnect(self, close_code):
        pass

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            await self._send_error('Invalid JSON')
            return

        message = data.get('message', '').strip()
        conv_id = data.get('conversation_id')

        if not message:
            await self._send_error('Message cannot be empty')
            return

        # Get or create conversation
        conversation = await self._get_or_create_conversation(conv_id)

        # Save user message
        await self._save_message(conversation, 'user', message)

        # Auto title
        count = await self._message_count(conversation)
        if count == 1:
            title = self._generate_title(message)
            await self._set_title(conversation, title)
            await self._send({
                'type': 'title',
                'title': title,
                'conversation_id': conversation.id,
            })

        # Get chat history
        history = await self._get_history(conversation)

        # Tool detection
        tool_context = await self._run_tool(message)

        # Send typing indicator
        await self._send({'type': 'typing_start'})

        # Stream from Groq
        full_response = ''
        try:
            client = Groq(api_key=settings.GROQ_API_KEY)

            chat_messages = [{"role": "system", "content": AIRA_SYSTEM_PROMPT}]
            for msg in history:
                chat_messages.append({"role": msg['role'], "content": msg['content']})

            # Inject tool result into last user message
            if tool_context and chat_messages and chat_messages[-1]['role'] == 'user':
                chat_messages[-1]['content'] += tool_context
            elif tool_context:
                chat_messages.append({"role": "user", "content": message + tool_context})

            stream = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=chat_messages,
                max_tokens=4096,
                temperature=0.7,
                stream=True,
            )

            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    token = delta.content
                    token = token.replace('\\u003D', '=').replace('\\u003C', '<').replace('\\u003E', '>').replace('\\u0026', '&')
                    full_response += token
                    await self._send({'type': 'token', 'token': token})

        except Exception as e:
            logger.exception("Streaming error")
            await self._send_error(str(e))
            return

        # Save full AI response
        await self._save_message(conversation, 'assistant', full_response)

        # Signal done
        await self._send({'type': 'done', 'conversation_id': conversation.id})

    # DB helpers

    @database_sync_to_async
    def _run_tool(self, message):
        try:
            if not TOOLS_OK:
                return ''
            tool_request = detect_tool_request(message)
            if tool_request['tool'] == 'calculator':
                calc = run_calculator(tool_request['input'])
                if calc['success']:
                    return f"\n\nCALCULATOR RESULT: {calc['formatted']}"
                return f"\n\nCALCULATOR ERROR: {calc['error']}"
            elif tool_request['tool'] == 'weather':
                weather = get_weather(tool_request['input'])
                return f"\n\n{format_weather(weather)}"
            elif tool_request['tool'] == 'python':
                py_result = run_python(tool_request['input'])
                return f"\n\nPYTHON EXECUTION RESULT:\n{format_python_result(py_result)}"
            return ''
        except Exception:
            return ''

    @database_sync_to_async
    def _get_or_create_conversation(self, conv_id):
        if conv_id:
            try:
                return Conversation.objects.get(id=conv_id, user=self.user)
            except Conversation.DoesNotExist:
                pass
        return Conversation.objects.create(user=self.user)

    @database_sync_to_async
    def _save_message(self, conversation, role, content):
        return Message.objects.create(
            conversation=conversation, role=role, content=content
        )

    @database_sync_to_async
    def _message_count(self, conversation):
        return conversation.messages.count()

    @database_sync_to_async
    def _set_title(self, conversation, title):
        conversation.title = title
        conversation.save()

    @database_sync_to_async
    def _get_history(self, conversation):
        msgs = list(conversation.messages.order_by('-created_at')[:20])
        msgs.reverse()
        return [{'role': m.role, 'content': m.content} for m in msgs]

    def _generate_title(self, msg):
        words = msg.strip().split()
        t = ' '.join(words[:7])
        return (t + '...') if len(words) > 7 else t

    async def _send(self, data):
        await self.send(text_data=json.dumps(data, ensure_ascii=False))

    async def _send_error(self, error):
        await self._send({'type': 'error', 'message': error})
