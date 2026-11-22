# -*- coding: utf-8 -*-
"""Export/import av eLearning-kurser — modulens huvudfunktion.

Wizarden ``elearning.export.import`` skriver en kurs till XML och läser
tillbaka den. Testet går genom kedjan som faktiskt används: skapa en kurs
med en slide, exportera, importera, och jämför innehållet.

Fälten som exporteras styrs av ``_get_whitelist_config`` — testet läser
samma konfiguration i stället för att lista fälten igen, så att en ändrad
vitlista inte tyst gör testet meningslöst.
"""

import base64
import xml.etree.ElementTree as ET

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestElearningExportImport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Wizard = cls.env['elearning.export.import']
        cls.Channel = cls.env['slide.channel']

        cls.course = cls.Channel.create({
            'name': 'Exporterad kurs',
            'description': 'En kurs som ska exporteras och importeras.',
            'channel_type': 'training',
            'slide_ids': [(0, 0, {
                'name': 'Lektion ett',
                'slide_category': 'article',
                'sequence': 1,
                'html_content': '<p>Innehåll i lektionen.</p>',
            })],
        })

    def _export_xml(self, courses=None):
        wizard = self.Wizard.create({
            'course_ids': [(6, 0, (courses or self.course).ids)],
        })
        return wizard._generate_xml()

    # ── Export ───────────────────────────────────────────────────────

    def test_wizard_model_loads(self):
        """Modulen ska registrera wizarden med rätt modellnamn."""
        self.assertEqual(self.Wizard._name, 'elearning.export.import')
        self.assertIn('course_ids', self.Wizard._fields)
        self.assertIn('data_file', self.Wizard._fields)

    def test_export_produces_parseable_xml(self):
        """Exporten ska ge välformad XML med rätt rot och metadata."""
        xml_content = self._export_xml()
        root = ET.fromstring(xml_content.encode('utf-8'))

        self.assertEqual(root.tag, 'elearning_export')
        self.assertEqual(root.get('version'), '1.0')
        self.assertEqual(root.find('total_courses').text, '1')
        self.assertIsNotNone(root.find('export_date'))

    def test_export_contains_the_course(self):
        """Kursen ska finnas som ett <course>-element med sitt id."""
        root = ET.fromstring(self._export_xml().encode('utf-8'))
        courses = root.findall('course')
        self.assertEqual(len(courses), 1)
        self.assertEqual(courses[0].get('id'), str(self.course.id))

    def test_export_writes_whitelisted_fields(self):
        """Varje fält i vitlistan ska hamna i XML:en.

        Fältet skrivs bara om det har ett värde, så testet kräver att de
        fält som kursen faktiskt har värden på finns med.
        """
        root = ET.fromstring(self._export_xml().encode('utf-8'))
        exported = {f.get('name') for f in root.find('course').findall('field')}

        whitelist = self.Wizard._get_whitelist_config()
        for field_name in ('name', 'description', 'channel_type'):
            self.assertIn(field_name, whitelist)
            self.assertIn(field_name, exported)

    def test_export_writes_the_slide(self):
        """Kursens slides exporteras som en one2many med sina fält."""
        root = ET.fromstring(self._export_xml().encode('utf-8'))
        slide_field = root.find("course/field[@name='slide_ids']")
        self.assertIsNotNone(slide_field)

        records = slide_field.findall('record')
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].get('model'), 'slide.slide')

        names = {f.get('name') for f in records[0].findall('field')}
        self.assertIn('name', names)
        self.assertIn('html_content', names)

    def test_export_without_courses_is_refused(self):
        """Utan valda kurser ska exporten avbrytas, inte skriva tom XML."""
        wizard = self.Wizard.create({})
        with self.assertRaises(UserError):
            wizard.action_export()

    def test_action_export_returns_a_download(self):
        """action_export ska lägga XML:en i en bilaga och returnera en URL."""
        wizard = self.Wizard.create({'course_ids': [(6, 0, self.course.ids)]})
        action = wizard.action_export()

        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.assertIn('/web/content/', action['url'])

        attachment = self.env['ir.attachment'].search([
            ('res_model', '=', self.Wizard._name),
            ('res_id', '=', wizard.id),
        ], limit=1)
        self.assertTrue(attachment)
        self.assertEqual(attachment.mimetype, 'application/xml')

    # ── Import ───────────────────────────────────────────────────────

    def test_import_roundtrip_creates_a_course(self):
        """Exporterad XML ska gå att importera tillbaka till en ny kurs."""
        xml_content = self._export_xml()
        before = self.Channel.search_count([])

        wizard = self.Wizard.create({
            'data_file': base64.b64encode(xml_content.encode('utf-8')),
            'filename': 'export.xml',
        })
        action = wizard.action_import()

        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(self.Channel.search_count([]), before + 1)

        imported = self.Channel.search([('name', '=', self.course.name)],
                                       order='id desc', limit=1)
        self.assertTrue(imported)
        self.assertNotEqual(imported.id, self.course.id)
        self.assertEqual(imported.description, self.course.description)

    def test_import_roundtrip_keeps_the_slide(self):
        """Sliden ska följa med i rundturen."""
        xml_content = self._export_xml()
        wizard = self.Wizard.create({
            'data_file': base64.b64encode(xml_content.encode('utf-8')),
        })
        wizard.action_import()

        imported = self.Channel.search([('name', '=', self.course.name)],
                                       order='id desc', limit=1)
        self.assertEqual(len(imported.slide_ids), 1)
        self.assertEqual(imported.slide_ids.name, 'Lektion ett')

    def test_import_without_file_is_refused(self):
        """Utan fil ska importen avbrytas."""
        wizard = self.Wizard.create({})
        with self.assertRaises(UserError):
            wizard.action_import()

    def test_import_of_broken_xml_is_refused(self):
        """Trasig XML ska ge UserError, inte en traceback ut till användaren."""
        wizard = self.Wizard.create({
            'data_file': base64.b64encode(b'<elearning_export><course>'),
        })
        with self.assertRaises(UserError):
            wizard.action_import()

    # ── Hjälpmetoder ─────────────────────────────────────────────────

    def test_resolve_reference_handles_unknown_ref(self):
        """En okänd referens ska ge False, inte krascha importen."""
        wizard = self.Wizard.create({})
        self.assertFalse(wizard._resolve_reference('no.such.model-999999'))
        self.assertFalse(wizard._resolve_reference(''))

    def test_attachment_placeholder_is_replaced(self):
        """{{ATT:...}}-platshållare byts mot bilagans URL vid import."""
        wizard = self.Wizard.create({})
        mapping = {'att_abc123': {'url': '/web/image/4711', 'attachment': None}}

        result = wizard._replace_attachment_placeholders(
            '<img src="{{ATT:att_abc123}}"/>', mapping)

        self.assertEqual(result, '<img src="/web/image/4711"/>')

    def test_unknown_attachment_placeholder_is_kept(self):
        """En platshållare utan bilaga lämnas orörd — tyst borttagning vore värre."""
        wizard = self.Wizard.create({})
        result = wizard._replace_attachment_placeholders(
            '<img src="{{ATT:att_missing}}"/>', {})
        self.assertEqual(result, '<img src="{{ATT:att_missing}}"/>')
