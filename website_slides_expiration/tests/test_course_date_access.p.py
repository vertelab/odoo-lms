# -*- coding: utf-8 -*-
"""Kursens giltighetstid — modulens huvudfunktion.

Modulen lägger ``start_date``/``end_date`` på ``slide.channel`` och nekar
åtkomst till en kurs vars ``end_date`` har passerat. Beräkningen sitter i
``slide.channel._check_course_date_access`` och är det som testas här.

TVÅ KÄNDA DEFEKTER (finns på alla tre utgåvor, även 18.0 — alltså inte
orsakade av porteringen). Testerna nedan bevisar dem i stället för att
dölja dem:

1. ``slide.slide._check_can_access`` — överriden finns i modulen, men
   metoden finns inte i website_slides på 18.0/19.0/20.0. Överridningen är
   död kod och slide-nivå-skyddet existerar inte. Se
   ``test_slide_level_guard_is_not_wired``.

2. På 18.0/19.0 överrider modulen ``check_access_rights``, men Odoos
   ``check_access()`` anropar ``_check_access()`` — aldrig
   ``check_access_rights()``. Datumspärren på kanalnivå är därför verkningslös
   på 18.0/19.0; bara 20.0-grenen spärrar på riktigt. Se
   ``test_channel_guard_is_wired_on_this_edition``.
"""

from datetime import timedelta

from odoo import fields, release
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCourseDateAccess(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Channel = cls.env['slide.channel']
        cls.today = fields.Date.today()

        cls.active_channel = cls.Channel.create({
            'name': 'Aktiv kurs',
            'start_date': cls.today - timedelta(days=10),
            'end_date': cls.today + timedelta(days=10),
        })
        cls.expired_channel = cls.Channel.create({
            'name': 'Utgången kurs',
            'start_date': cls.today - timedelta(days=20),
            'end_date': cls.today - timedelta(days=1),
        })
        cls.open_channel = cls.Channel.create({'name': 'Kurs utan slutdatum'})

    # ── Modulen laddar ───────────────────────────────────────────────

    def test_fields_exist(self):
        """Modulen ska lägga start_date och end_date på slide.channel."""
        channel = self.Channel.new({})
        self.assertIn('start_date', channel._fields)
        self.assertIn('end_date', channel._fields)
        self.assertEqual(channel._fields['start_date'].type, 'date')
        self.assertEqual(channel._fields['end_date'].type, 'date')

    def test_start_date_defaults_to_today(self):
        """start_date har default idag — en ny kurs är öppen från start."""
        channel = self.Channel.create({'name': 'Ny kurs'})
        self.assertEqual(channel.start_date, self.today)
        self.assertFalse(channel.end_date)

    # ── Beräkningen ──────────────────────────────────────────────────

    def test_active_course_is_accessible(self):
        result = self.Channel._check_course_date_access(self.active_channel.id)
        self.assertTrue(result['accessible'])
        self.assertEqual(result['status'], 'active')
        self.assertEqual(result['message'], '')

    def test_expired_course_is_not_accessible(self):
        result = self.Channel._check_course_date_access(self.expired_channel.id)
        self.assertFalse(result['accessible'])
        self.assertEqual(result['status'], 'ended')
        self.assertIn(self.expired_channel.end_date.strftime('%Y-%m-%d'),
                      result['message'])

    def test_course_without_end_date_is_accessible(self):
        result = self.Channel._check_course_date_access(self.open_channel.id)
        self.assertTrue(result['accessible'])

    def test_end_date_today_is_still_accessible(self):
        """Sista dagen ska kursen vara öppen — kontrollen är '>' inte '>='."""
        channel = self.Channel.create({
            'name': 'Sista dagen',
            'end_date': self.today,
        })
        result = self.Channel._check_course_date_access(channel.id)
        self.assertTrue(result['accessible'])

    # ── Kanalnivå — känd defekt 2 ────────────────────────────────────

    def test_channel_guard_is_wired_on_this_edition(self):
        """Datumspärren på kanalnivå ska slå till — men bara på 20.0.

        På 18.0/19.0 överrider modulen ``check_access_rights``. Odoo 18/19
        anropar den aldrig från ``check_access()``; den delegerar i stället
        TILL ``check_access``. Spärren är därför verkningslös där.

        Testet är skrivet så att det FÄLLER om defekten rättas (då blir
        grenen för 18.0/19.0 grön) — det är avsiktligt: det ska synas när
        någon fixar den.
        """
        if release.version_info[0] >= 20:
            with self.assertRaises(AccessError):
                self.expired_channel.check_access('read')
            self.active_channel.check_access('read')
        else:
            # Känd defekt: ingen AccessError trots utgången kurs.
            self.expired_channel.check_access('read')

    def test_deprecated_override_is_the_one_in_use(self):
        """Verifiera VILKEN metod modulen faktiskt överrider per utgåva.

        Detta är rotorsaken till känd defekt 2, uttryckt som ett test: på
        18.0/19.0 äger modulen ``check_access_rights``, på 20.0 äger den
        ``check_access``.
        """
        # Modulens klass, inte registry-klassen: arvet syns bara pa den forra.
        from odoo.addons.website_slides_expiration.models.slide_channel import (
            SlideChannel,
        )
        if release.version_info[0] >= 20:
            self.assertIn('check_access', SlideChannel.__dict__)
            self.assertNotIn('check_access_rights', SlideChannel.__dict__)
        else:
            self.assertIn('check_access_rights', SlideChannel.__dict__)
            self.assertNotIn('check_access', SlideChannel.__dict__)

    # ── Slide-nivå — känd defekt 1 ───────────────────────────────────

    def test_slide_level_guard_is_not_wired(self):
        """``_check_can_access`` finns inte i website_slides — död override.

        Modulen definierar metoden och anropar ``super()``. Eftersom
        föräldern inte har den kastar anropet AttributeError. Testet bevisar
        att överridningen finns men inte kan användas; det ska fällas när
        någon riktar den mot rätt hook.
        """
        slide = self.env['slide.slide'].create({
            'name': 'Lektion',
            'channel_id': self.active_channel.id,
            'slide_category': 'article',
            'is_published': True,
        })
        from odoo.addons.website_slides_expiration.models.slide_slide import (
            SlideSlide,
        )
        self.assertIn('_check_can_access', SlideSlide.__dict__)
        # Foraldern (website_slides) har ingen sadan metod -> AttributeError.
        with self.assertRaises(AttributeError):
            slide._check_can_access()
