import json
import logging
import threading
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_http_methods
from django.http import JsonResponse
from .models import Conversation, Message, UploadedFile, UserMemory, KnowledgeBase
from .ai_service import get_ai_response, generate_title
from .file_processor import (
    validate_file, detect_file_type,
    extract_pdf_text, prepare_pdf_context,
    extract_image_text_ocr, image_to_base64, get_image_info,
    extract_docx_text,
)
from accounts.models import UserProfile

logger = logging.getLogger(__name__)

try:
    from .tools import detect_tool_request, run_calculator, get_weather, format_weather, run_python, format_python_result
    TOOLS_OK = True
except Exception as e:
    TOOLS_OK = False
    logger.warning(f"Tools disabled: {e}")

try:
    from .memory_service import (
        save_message_to_memory, build_rag_context,
        get_user_personalization, extract_and_save_user_facts,
        add_to_knowledge_base, search_knowledge_base,
        semantic_search_history, compare_documents,
    )
    MEMORY_OK = True
except Exception as e:
    logger.warning(f"Memory service disabled: {e}")
    MEMORY_OK = False


def get_profile(user):
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


@login_required
def index(request):
    conversations = Conversation.objects.filter(user=request.user)
    # Always show empty welcome screen on login - no active conversation
    return render(request, 'chat/index.html', {
        'conversations': conversations,
        'active_conversation': None,
        'messages_list': [],
        'profile': get_profile(request.user),
    })


@login_required
def conversation_view(request, conv_id):
    conversations = Conversation.objects.filter(user=request.user)
    active = get_object_or_404(Conversation, id=conv_id, user=request.user)
    return render(request, 'chat/index.html', {
        'conversations': conversations,
        'active_conversation': active,
        'messages_list': active.messages.all(),
        'profile': get_profile(request.user),
    })


@login_required
@require_POST
def new_conversation(request):
    conv = Conversation.objects.create(user=request.user)
    return redirect('chat:conversation', conv_id=conv.id)


@login_required
@require_POST
def send_message(request):
    content = request.POST.get('message', '').strip()
    conv_id = request.POST.get('conversation_id') or None
    uploaded_file = request.FILES.get('file')
    file2 = request.FILES.get('file2')

    if not content and not uploaded_file:
        return JsonResponse({'success': False, 'error': 'Message cannot be empty.'})

    if uploaded_file:
        v = validate_file(uploaded_file)
        if not v['valid']:
            return JsonResponse({'success': False, 'error': v['error']})
    if file2:
        v = validate_file(file2)
        if not v['valid']:
            return JsonResponse({'success': False, 'error': v['error']})

    if conv_id:
        try:
            conversation = Conversation.objects.get(id=conv_id, user=request.user)
        except Conversation.DoesNotExist:
            conversation = Conversation.objects.create(user=request.user)
    else:
        conversation = Conversation.objects.create(user=request.user)

    # Document comparison
    if uploaded_file and file2:
        return handle_document_comparison(request, conversation, uploaded_file, file2, content)

    image_base64 = None
    image_mime = None
    ocr_text = None
    file_context = ""
    file_note = ""
    file_type = "none"
    ai_mode = "chat"
    display_content = content
    pdf_result = {}
    docx_result = {}

    if uploaded_file:
        file_data = uploaded_file.read()
        file_name = uploaded_file.name
        mime = uploaded_file.content_type
        file_type = detect_file_type(uploaded_file)

        if file_type == 'pdf':
            ai_mode = 'pdf'
            file_note = f"📄 {file_name}"
            display_content = content or f"Explain this PDF: {file_name}"
            pdf_result = extract_pdf_text(file_data, file_name)
            if pdf_result['success']:
                pdf_ctx = prepare_pdf_context(pdf_result['text'])
                page_info = f"({pdf_result.get('page_count', '?')} pages)"
                file_context = f"\n\n{'='*50}\n📄 PDF: {file_name} {page_info}\n{'='*50}\n\n{pdf_ctx}\n\n{'='*50}\n"
                if MEMORY_OK:
                    try:
                        personalization = get_user_personalization(request.user.id)
                    except Exception:
                        pass
            else:
                file_context = f"\n\n[PDF Error: {pdf_result.get('error')}]"

        elif file_type == 'image':
            ai_mode = 'image'
            file_note = f"🖼️ {file_name}"
            display_content = content or "Analyze this image in detail."
            image_base64 = image_to_base64(file_data, mime)
            image_mime = mime
            ocr_result = extract_image_text_ocr(file_data)
            if ocr_result['success'] and ocr_result['text']:
                ocr_text = ocr_result['text']
                file_context = f"\n\n[OCR Text: {ocr_text[:2000]}]"
            try:
                img_info = get_image_info(file_data)
                if img_info.get('width'):
                    file_context += f"\n[{img_info['width']}x{img_info['height']}]"
            except Exception:
                pass

        elif file_type == 'docx':
            ai_mode = 'pdf'
            file_note = f"📝 {file_name}"
            display_content = content or f"Explain this Word document: {file_name}"
            docx_result = extract_docx_text(file_data, file_name)
            if docx_result['success']:
                file_context = f"\n\n{'='*50}\n📝 WORD DOCUMENT: {file_name}\n{'='*50}\n\n{docx_result['text'][:12000]}\n\n{'='*50}\n"
                if MEMORY_OK:
                    try:
                        add_to_knowledge_base(request.user.id, file_name, docx_result['text'], file_name)
                    except Exception:
                        pass
            else:
                file_context = f"\n\n[DOCX Error: {docx_result.get('error')}]"

        elif file_type in ('code', 'text'):
            try:
                text_content = file_data.decode('utf-8', errors='ignore')
                ext = file_name.split('.')[-1]
                file_note = f"📎 {file_name}"
                display_content = content or f"Explain this file: {file_name}"
                file_context = f"\n\n{'='*50}\n📎 FILE: {file_name}\n{'='*50}\n\n```{ext}\n{text_content[:12000]}\n```\n\n{'='*50}\n"
            except Exception as e:
                file_context = f"\n\n[File read error: {e}]"
                file_note = f"📎 {file_name}"

        try:
            UploadedFile.objects.create(
                conversation=conversation,
                user=request.user,
                original_name=file_name,
                file_type=file_type,
                file_size=len(file_data),
                extracted_text=(
                    pdf_result.get('text', '')[:50000] if file_type == 'pdf'
                    else docx_result.get('text', '')[:50000] if file_type == 'docx'
                    else ''
                ),
            )
        except Exception:
            pass

    # Tool detection and execution
    tool_result_text = ''
    tool_used = None

    if TOOLS_OK and content and not uploaded_file:
        try:
            tool_request = detect_tool_request(content)
            if tool_request['tool'] == 'calculator':
                calc = run_calculator(tool_request['input'])
                if calc['success']:
                    tool_result_text = f"\n\nCALCULATOR RESULT: {calc['formatted']}"
                    tool_used = 'calculator'
                else:
                    tool_result_text = f"\n\nCALCULATOR ERROR: {calc['error']}"
            elif tool_request['tool'] == 'weather':
                weather = get_weather(tool_request['input'])
                tool_result_text = f"\n\n{format_weather(weather)}"
                tool_used = 'weather'
            elif tool_request['tool'] == 'python':
                py_result = run_python(tool_request['input'])
                tool_result_text = f"\n\nPYTHON EXECUTION RESULT:\n{format_python_result(py_result)}"
                tool_used = 'python'
        except Exception as e:
            logger.warning(f"Tool error: {e}")

    # Save user message
    user_msg_text = (f"{file_note}\n{display_content}" if file_note else display_content).strip()
    user_msg_text = user_msg_text.replace('\\u000A', '\n').replace('\\u0009', '\t')
    Message.objects.create(conversation=conversation, role='user', content=user_msg_text)

    if conversation.messages.count() == 1:
        conversation.title = generate_title(content or (uploaded_file.name if uploaded_file else 'New Chat'))
        conversation.save()

    # Build history
    history = list(conversation.messages.order_by('-created_at')[:20])
    history.reverse()

    # RAG context
    
    if MEMORY_OK:
        try:
            personalization = get_user_personalization(request.user.id)
            if not file_context:
                rag_context = build_rag_context(request.user.id, display_content)
        except Exception as e:
            logger.warning(f"RAG error: {e}")

    # Build AI messages
    ai_messages = []
    for i, m in enumerate(history):
        is_last = (i == len(history) - 1 and m.role == 'user')
        if is_last:
            ai_messages.append({'role': 'user', 'content': display_content + file_context + tool_result_text})
        else:
            ai_messages.append({'role': m.role, 'content': m.content})

    # Call AI
    result = get_ai_response(
        messages=ai_messages,
        image_base64=image_base64,
        image_mime=image_mime,
        mode=ai_mode,
        ocr_text=ocr_text,
        personalization=personalization,
        rag_context=rag_context,
    )

    if not result['success']:
        return JsonResponse({
            'success': False,
            'error': result['error'],
            'conversation_id': conversation.id,
        })

    clean = result['content'].replace('\\u000A', '\n').replace('\\u0009', '\t').replace('\\u003D', '=').replace('\\u003C', '<').replace('\\u003E', '>').replace('\\u0026', '&')
    ai_msg = Message.objects.create(
        conversation=conversation,
        role='assistant',
        content=clean,
        tokens_used=result.get('tokens', 0),
    )
    conversation.save()

    # Save memory in background thread
    if MEMORY_OK:
        def save_bg():
            try:
                save_message_to_memory(request.user.id, conversation.id, 'user', display_content)
                save_message_to_memory(request.user.id, conversation.id, 'assistant', clean)
                recent = list(conversation.messages.order_by('-created_at')[:6])
                recent.reverse()
                extract_and_save_user_facts(
                    request.user.id,
                    [{'role': m.role, 'content': m.content} for m in recent]
                )
            except Exception:
                pass
        threading.Thread(target=save_bg, daemon=True).start()

    return JsonResponse({
        'success': True,
        'message': clean,
        'conversation_id': conversation.id,
        'conversation_title': conversation.title,
        'message_id': ai_msg.id,
        'file_note': file_note,
        'file_type': file_type,
    })


def handle_document_comparison(request, conversation, file1, file2, user_query):
    data1 = file1.read()
    data2 = file2.read()

    def extract(data, f):
        ft = detect_file_type(f)
        if ft == 'pdf':
            r = extract_pdf_text(data, f.name)
            return r.get('text', '') if r['success'] else ''
        elif ft == 'docx':
            r = extract_docx_text(data, f.name)
            return r.get('text', '') if r['success'] else ''
        else:
            try:
                return data.decode('utf-8', errors='ignore')
            except Exception:
                return ''

    text1 = extract(data1, file1)
    text2 = extract(data2, file2)

    if not text1 or not text2:
        return JsonResponse({'success': False, 'error': 'Could not extract text from one or both files.'})

    if MEMORY_OK:
        comparison_prompt = compare_documents(text1, text2, file1.name, file2.name)
    else:
        comparison_prompt = f"Compare these two documents:\n\nDOC 1 ({file1.name}):\n{text1[:6000]}\n\nDOC 2 ({file2.name}):\n{text2[:6000]}\n\nProvide a detailed comparison."

    if user_query:
        comparison_prompt += f"\n\nUser question: {user_query}"

    user_msg = f"📄 Compare: {file1.name} vs {file2.name}"
    if user_query:
        user_msg += f"\n{user_query}"

    Message.objects.create(conversation=conversation, role='user', content=user_msg)
    if conversation.messages.count() == 1:
        conversation.title = f"Compare: {file1.name[:20]} vs {file2.name[:20]}"
        conversation.save()

    result = get_ai_response(
        messages=[{'role': 'user', 'content': comparison_prompt}],
        mode='pdf'
    )
    if not result['success']:
        return JsonResponse({'success': False, 'error': result['error']})

    clean = result['content'].replace('\\u000A', '\n')
    ai_msg = Message.objects.create(
        conversation=conversation,
        role='assistant',
        content=clean,
        tokens_used=result.get('tokens', 0)
    )
    conversation.save()

    return JsonResponse({
        'success': True,
        'message': clean,
        'conversation_id': conversation.id,
        'conversation_title': conversation.title,
        'message_id': ai_msg.id,
        'file_note': f"📄 {file1.name} vs 📄 {file2.name}",
        'file_type': 'comparison',
    })


@login_required
def knowledge_base_view(request):
    kb_items = KnowledgeBase.objects.filter(user=request.user)
    return render(request, 'chat/knowledge_base.html', {
        'kb_items': kb_items,
        'profile': get_profile(request.user),
    })


@login_required
def semantic_search_api(request):
    query = request.GET.get('q', '').strip()
    if not query or not MEMORY_OK:
        return JsonResponse({'results': []})
    try:
        results = semantic_search_history(request.user.id, query)
        return JsonResponse({'success': True, 'results': results[:10]})
    except Exception:
        return JsonResponse({'results': []})


@login_required
@require_http_methods(['DELETE'])
def delete_conversation(request, conv_id):
    conv = get_object_or_404(Conversation, id=conv_id, user=request.user)
    conv.delete()
    return JsonResponse({'success': True})


@login_required
@require_POST
def rename_conversation(request, conv_id):
    conv = get_object_or_404(Conversation, id=conv_id, user=request.user)
    try:
        data = json.loads(request.body)
        title = data.get('title', '').strip()
        if not title:
            return JsonResponse({'error': 'Title cannot be empty.'}, status=400)
        conv.title = title[:200]
        conv.save()
        return JsonResponse({'success': True, 'title': conv.title})
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)


@login_required
@require_POST
def pin_conversation(request, conv_id):
    conv = get_object_or_404(Conversation, id=conv_id, user=request.user)
    conv.is_pinned = not conv.is_pinned
    conv.save()
    return JsonResponse({'success': True, 'pinned': conv.is_pinned})


@login_required
@require_POST
def clear_conversation(request, conv_id):
    conv = get_object_or_404(Conversation, id=conv_id, user=request.user)
    conv.messages.all().delete()
    conv.title = 'New Chat'
    conv.save()
    return JsonResponse({'success': True})