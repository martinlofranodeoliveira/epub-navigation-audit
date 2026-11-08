import unittest

from epub_navigation_audit.model import AuditLimits, Issues, StopAudit
from epub_navigation_audit.xmlsafe import XmlBudget, parse_xml


class XmlTests(unittest.TestCase):
    def budget(self, **kwargs):
        return XmlBudget(AuditLimits(**kwargs), Issues(1000))

    def test_utf8_utf16_structure_without_prose(self):
        text = '<?xml version="1.0"?><r xmlns:p="urn:test">PROSE<p:a id="é">MORE</p:a>TAIL</r>'
        for data in (text.encode('utf-8'), text.encode('utf-16')):
            with self.subTest(data=data[:4]):
                budget = self.budget()
                root = parse_xml(data, path='x.xml', budget=budget)
                self.assertEqual(root[0].tag, '{urn:test}a')
                self.assertEqual(root[0].get('id'), 'é')
                self.assertIsNone(root.text)
                self.assertIsNone(root[0].text)
                self.assertIsNone(root[0].tail)
                self.assertEqual(budget.nodes, 2)
                self.assertEqual(budget.issues.items, [])

    def test_dtd_even_innocuous_is_incomplete(self):
        for data in [b'<!DOCTYPE r><r/>',
                     b'<!DOCTYPE r SYSTEM "file:///private/canary"><r/>',
                     b'<!DOCTYPE r [<!ENTITY x SYSTEM "https://example.invalid/secret">]><r>&x;</r>']:
            budget = self.budget()
            self.assertIsNone(parse_xml(data, path='x.xml', budget=budget))
            self.assertTrue(budget.issues.partial)
            self.assertFalse(budget.issues.error)
            self.assertEqual(budget.issues.items[0].code, 'xml_declaration_unsupported')
            self.assertNotIn('canary', str(budget.issues.items))
            self.assertNotIn('secret', str(budget.issues.items))

    def test_malformed_errors_are_sanitized(self):
        budget = self.budget()
        self.assertIsNone(parse_xml(b'<SECRET><broken></SECRET>', path='x.xml', budget=budget))
        self.assertTrue(budget.issues.error)
        self.assertTrue(budget.issues.partial)
        self.assertEqual(budget.issues.items[0].code, 'xml_invalid')
        self.assertNotIn('SECRET', str(budget.issues.items))

    def test_base_halts_semantics_without_fabricating_paths(self):
        for data in [b'<r xml:base="elsewhere/"/>',
                     b'<r><child xml:base="https://example.invalid/"/></r>',
                     b'<html xmlns="http://www.w3.org/1999/xhtml"><head><base href="elsewhere/"/></head></html>']:
            budget = self.budget()
            self.assertIsNone(parse_xml(data, path='x.xml', budget=budget))
            self.assertEqual(budget.issues.items[0].code, 'xml_base_unsupported')
            self.assertTrue(budget.issues.partial)
            self.assertFalse(budget.issues.error)

    def test_xinclude_is_not_executed(self):
        budget = self.budget()
        self.assertIsNone(parse_xml(b'<r xmlns:i="http://www.w3.org/2001/XInclude"><i:include href="file:///private/canary"/></r>', path='x.xml', budget=budget))
        self.assertEqual(budget.issues.items[0].code, 'xinclude_forbidden')

    def test_global_nodes_and_depth_stop_before_retry(self):
        budget = self.budget(max_xml_nodes=3)
        self.assertIsNotNone(parse_xml(b'<r><a/></r>', path='a.xml', budget=budget))
        with self.assertRaises(StopAudit):
            parse_xml(b'<r><a/></r>', path='b.xml', budget=budget)
        self.assertTrue(budget.exhausted)
        nodes = budget.nodes
        with self.assertRaises(StopAudit):
            parse_xml(b'<r/>', path='c.xml', budget=budget)
        self.assertEqual(budget.nodes, nodes)
        self.assertEqual(budget.issues.items[0].code, 'xml_node_limit')
        budget = self.budget(max_xml_depth=2)
        with self.assertRaises(StopAudit):
            parse_xml(b'<r><a><b/></a></r>', path='deep.xml', budget=budget)
        self.assertEqual(budget.issues.items[0].code, 'xml_depth_limit')

    def test_physical_xml_bytes_limit_including_utf16(self):
        budget = self.budget(max_xml_bytes=9)
        with self.assertRaises(StopAudit):
            parse_xml('<r/>'.encode('utf-16'), path='x.xml', budget=budget)
        self.assertEqual(budget.issues.items[0].code, 'xml_size_limit')
