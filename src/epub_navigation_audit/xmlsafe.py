"""DTD-free XML structure capture with global element and depth budgets."""
import xml.etree.ElementTree as ET

from defusedxml.ElementTree import DefusedXMLParser
from defusedxml.common import DTDForbidden, EntitiesForbidden, ExternalReferenceForbidden

from .model import StopAudit


XML_BASE = '{http://www.w3.org/XML/1998/namespace}base'
XHTML_BASE = '{http://www.w3.org/1999/xhtml}base'
XINCLUDE = '{http://www.w3.org/2001/XInclude}include'


class XmlBudget:
    def __init__(self, limits, issues):
        self.limits = limits
        self.issues = issues
        self.nodes = 0
        self.exhausted = False

    def stop(self, code, message, path):
        self.exhausted = True
        self.issues.stop('incomplete', code, message, path)


class _BoundedTree(ET.TreeBuilder):
    def __init__(self, budget, path):
        super().__init__()
        self.budget = budget
        self.path = path
        self.depth = 0

    def start(self, tag, attrs):
        if self.budget.nodes >= self.budget.limits.max_xml_nodes:
            self.budget.stop('xml_node_limit', 'O limite global de elementos XML foi atingido.', self.path)
        self.budget.nodes += 1
        self.depth += 1
        if self.depth > self.budget.limits.max_xml_depth:
            self.budget.stop('xml_depth_limit', 'O limite de profundidade XML foi atingido.', self.path)
        return super().start(tag, attrs)

    def end(self, tag):
        element = super().end(tag)
        self.depth -= 1
        return element

    def data(self, data):
        # Labels and chapter prose are outside this profile. Keeping only
        # structure/attributes also avoids retaining their text in the tree.
        pass


def parse_xml(data, *, path, budget):
    """Return structural XML, or None after a visible parse/profile finding."""
    if budget.exhausted:
        raise StopAudit
    if type(data) is not bytes:
        raise ValueError('A entrada XML deve ser bytes.')
    if len(data) > budget.limits.max_xml_bytes:
        budget.stop('xml_size_limit', 'O limite de bytes de um documento XML foi atingido.', path)
    parser = DefusedXMLParser(target=_BoundedTree(budget, path),
                             forbid_dtd=True, forbid_entities=True, forbid_external=True)
    try:
        parser.feed(data)
        root = parser.close()
    except (DTDForbidden, EntitiesForbidden, ExternalReferenceForbidden):
        budget.issues.add('incomplete', 'xml_declaration_unsupported',
                          'Uma declaração XML não é processada por este perfil seguro.', path)
        return None
    except (ET.ParseError, UnicodeError, LookupError, ValueError):
        budget.issues.partial = True
        budget.issues.add('error', 'xml_invalid', 'O documento XML não pôde ser interpretado.', path)
        return None
    for element in root.iter():
        if XML_BASE in element.attrib or element.tag == XHTML_BASE:
            budget.issues.add('incomplete', 'xml_base_unsupported',
                              'A resolução com base explícita não é processada por este perfil.', path)
            return None
        if element.tag == XINCLUDE:
            budget.issues.partial = True
            budget.issues.add('error', 'xinclude_forbidden',
                              'O documento contém inclusão XML fora do perfil EPUB.', path)
            return None
    return root
