"""Shared bounded profile and stable diagnostics."""
from dataclasses import dataclass


@dataclass(frozen=True)
class AuditLimits:
    max_archive_bytes: int = 33_554_432
    max_members: int = 4096
    max_xml_bytes: int = 2_097_152
    max_total_read_bytes: int = 16_777_216
    max_name_bytes: int = 1024
    max_xml_nodes: int = 100_000
    max_xml_depth: int = 128
    max_links: int = 20_000
    max_issues: int = 1000

    def __post_init__(self):
        ceilings = {'max_archive_bytes': 268_435_456, 'max_members': 20_000,
                    'max_xml_bytes': 16_777_216, 'max_total_read_bytes': 134_217_728,
                    'max_name_bytes': 4096, 'max_xml_nodes': 1_000_000,
                    'max_xml_depth': 512, 'max_links': 100_000, 'max_issues': 10_000}
        for name, maximum in ceilings.items():
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError('Limite inválido: ' + name)


class AuditError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class StopAudit(Exception):
    """A visible, already recorded budget or structural stop."""


@dataclass(frozen=True)
class Issue:
    severity: str
    code: str
    message: str
    path: str | None = None
    location: int | None = None


class Issues:
    def __init__(self, limit):
        self.limit = limit
        self.items = []
        self.error = False
        self.partial = False

    def add(self, severity, code, message, path=None, location=None):
        self.error |= severity == 'error'
        self.partial |= severity == 'incomplete'
        if len(self.items) >= self.limit - 1:
            self.partial = True
            rank = 'error' if self.error and not any(i.severity == 'error' for i in self.items) else 'incomplete'
            self.items.append(Issue(rank, 'issue_limit', 'O limite de achados interrompeu a auditoria; os diagnósticos são parciais.'))
            raise StopAudit
        self.items.append(Issue(severity, code, message, path, location))

    def stop(self, severity, code, message, path=None, location=None):
        self.partial = True
        self.add(severity, code, message, path, location)
        raise StopAudit


def sorted_issues(items):
    severity = {'error': 0, 'incomplete': 1, 'warning': 2}
    return sorted(items, key=lambda item: (severity[item.severity], item.path or '',
                                          item.location or 0, item.code, item.message))
