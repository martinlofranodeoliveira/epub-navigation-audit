"""A bounded local profile for inspecting EPUB 3 navigation references."""
__version__ = '1.0.0'

from .api import audit_epub
from .model import AuditError, AuditLimits
from .report import to_json, to_markdown

__all__ = ['AuditError', 'AuditLimits', 'audit_epub', 'to_json', 'to_markdown', '__version__']
