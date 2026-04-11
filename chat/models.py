from django.db import models
from django.contrib.auth.models import User
import os


class Conversation(models.Model):
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversations')
    title      = models.CharField(max_length=255, default='New Chat')
    is_pinned  = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_pinned', '-updated_at']

    def __str__(self):
        return f"{self.user.username} — {self.title}"


class Message(models.Model):
    ROLE_CHOICES = [('user', 'User'), ('assistant', 'Assistant')]

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    role         = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content      = models.TextField()
    tokens_used  = models.IntegerField(default=0)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"[{self.role}] {self.content[:60]}"


class UploadedFile(models.Model):
    FILE_TYPE_CHOICES = [
        ('pdf',   'PDF Document'),
        ('image', 'Image'),
        ('code',  'Code File'),
        ('text',  'Text File'),
        ('docx',  'Word Document'),
        ('other', 'Other'),
    ]

    conversation   = models.ForeignKey(Conversation, on_delete=models.CASCADE,
                                       related_name='uploaded_files', null=True, blank=True)
    user           = models.ForeignKey(User, on_delete=models.CASCADE)
    file           = models.FileField(upload_to='uploads/%Y/%m/%d/')
    original_name  = models.CharField(max_length=255)
    file_type      = models.CharField(max_length=10, choices=FILE_TYPE_CHOICES)
    file_size      = models.IntegerField(default=0)
    extracted_text = models.TextField(blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.original_name} ({self.file_type})"


# ── NEW: User AI Memory & Personalization ──────────────
class UserMemory(models.Model):
    """Stores long-term facts AI learns about the user"""
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='memories')
    memory     = models.TextField()           # e.g. "User prefers Python over JavaScript"
    category   = models.CharField(max_length=50, default='general')
    importance = models.IntegerField(default=1)  # 1-5
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-importance', '-updated_at']

    def __str__(self):
        return f"{self.user.username}: {self.memory[:60]}"


# ── NEW: Knowledge Base ────────────────────────────────
class KnowledgeBase(models.Model):
    """User's personal knowledge base documents"""
    user        = models.ForeignKey(User, on_delete=models.CASCADE, related_name='knowledge_base')
    title       = models.CharField(max_length=255)
    content     = models.TextField()
    source_file = models.CharField(max_length=255, blank=True)
    file_type   = models.CharField(max_length=20, blank=True)
    embedding_path = models.CharField(max_length=500, blank=True)  # path to FAISS index
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"{self.user.username} — {self.title}"


# ── NEW: Document Comparison ───────────────────────────
class DocumentComparison(models.Model):
    """Stores results of document comparisons"""
    user        = models.ForeignKey(User, on_delete=models.CASCADE)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE,
                                     null=True, blank=True)
    doc1_name   = models.CharField(max_length=255)
    doc2_name   = models.CharField(max_length=255)
    doc1_text   = models.TextField()
    doc2_text   = models.TextField()
    comparison_result = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.doc1_name} vs {self.doc2_name}"