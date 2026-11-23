# -*- coding: utf-8 -*-
"""Automatiska kursmail — modulens huvudfunktion.

Modulen lägger modellen ``slide.mail`` på en kurs: en mall plus ett
intervall som avgör när mailet ska gå. ``_compute_scheduled_date`` räknar
ut sändningstidpunkten och ``cron_run`` skickar de som förfallit.

Två saker styr testets form:

- ``tmp_start_date``/``tmp_end_date`` är ``Date``-fält, inte ``Datetime``.
  ``scheduled_date`` blir därför midnatt — jämförelser görs mot datumdelen.
- ``_send_mail`` mockas med ``unittest.mock.patch.object``. Utan mock skulle
  ``mail.compose.message`` försöka leverera på riktigt.
"""

from datetime import timedelta
from unittest.mock import patch

from odoo import fields, release
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSlideMail(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.SlideMail = cls.env['slide.mail']
        cls.Channel = cls.env['slide.channel']
        cls.partner = cls.env['res.partner'].create({
            'name': 'Kursdeltagare',
            'email': 'deltagare@example.com',
        })
        cls.template = cls.env['mail.template'].create({
            'name': 'Kursmall',
            'subject': 'Välkommen till kursen',
            'body_html': '<p>Hej</p>',
            'model_id': cls.env['ir.model']._get_id('slide.mail'),
        })
        cls.channel = cls.Channel.create({'name': 'Kurs med mail'})

    def _make_mail(self, **values):
        base = {
            'slide_channel_id': self.channel.id,
            'partner_id': self.partner.id,
            'template_ref': 'mail.template,%s' % self.template.id,
        }
        base.update(values)
        return self.SlideMail.create(base)

    # ── Modellen laddar ──────────────────────────────────────────────

    def test_model_loads(self):
        """Modulen ska registrera slide.mail med förväntade fält."""
        self.assertEqual(self.SlideMail._name, 'slide.mail')
        for field_name in ('slide_channel_id', 'partner_id', 'interval_nbr',
                           'interval_unit', 'interval_type', 'template_ref',
                           'scheduled_date', 'mail_done'):
            self.assertIn(field_name, self.SlideMail._fields, field_name)

    def test_channel_gets_the_one2many(self):
        """Kursen ska få slide_mail_ids så mailen syns på kursen."""
        self.assertIn('slide_mail_ids', self.Channel._fields)
        mail = self._make_mail()
        self.assertIn(mail, self.channel.slide_mail_ids)

    # ── Schemaläggning ───────────────────────────────────────────────

    def test_scheduled_date_is_computed_from_tmp_start_date(self):
        """before_event räknar bakåt från tmp_start_date med intervallet."""
        start = fields.Date.today() + timedelta(days=10)
        mail = self._make_mail(
            interval_type='before_event',
            interval_unit='days',
            interval_nbr=2,
            tmp_start_date=start,
        )
        self.assertEqual(mail.scheduled_date,
                         fields.Datetime.to_datetime(start) - timedelta(days=2))

    def test_scheduled_date_is_computed_from_tmp_end_date(self):
        """after_event räknar framåt från tmp_end_date."""
        end = fields.Date.today() + timedelta(days=5)
        mail = self._make_mail(
            interval_type='after_event',
            interval_unit='days',
            interval_nbr=3,
            tmp_end_date=end,
        )
        self.assertEqual(mail.scheduled_date,
                         fields.Datetime.to_datetime(end) + timedelta(days=3))

    def test_scheduled_date_is_false_without_a_date(self):
        """Utan tmp_start_date/tmp_end_date blir scheduled_date False."""
        mail = self._make_mail(interval_type='before_event',
                               interval_unit='days', interval_nbr=1)
        self.assertFalse(mail.scheduled_date)

    def test_interval_units_are_supported(self):
        """Alla enheter i _INTERVALS ska gå att räkna med."""
        start = fields.Date.today() + timedelta(days=30)
        base = fields.Datetime.to_datetime(start)
        for unit, delta in (
            ('hours', timedelta(hours=4)),
            ('days', timedelta(days=4)),
            ('weeks', timedelta(weeks=4)),
        ):
            mail = self._make_mail(
                interval_type='before_event',
                interval_unit=unit,
                interval_nbr=4,
                tmp_start_date=start,
            )
            self.assertEqual(mail.scheduled_date, base - delta, unit)

    def test_month_interval_moves_backwards(self):
        """Månader är inte fasta dagar — kontrollera riktning, inte exakt värde."""
        start = fields.Date.today() + timedelta(days=90)
        mail = self._make_mail(
            interval_type='before_event',
            interval_unit='months',
            interval_nbr=1,
            tmp_start_date=start,
        )
        self.assertLess(mail.scheduled_date, fields.Datetime.to_datetime(start))

    # ── Status ───────────────────────────────────────────────────────

    def test_mail_state_is_scheduled_before_sending(self):
        mail = self._make_mail(interval_type='before_event',
                               interval_unit='days', interval_nbr=1)
        self.assertEqual(mail.mail_state, 'scheduled')

    def test_mail_state_is_running_for_after_sub(self):
        """after_sub är registreringsbaserad och räknas som 'running'."""
        mail = self._make_mail(interval_type='after_sub',
                               interval_unit='days', interval_nbr=1)
        self.assertEqual(mail.mail_state, 'running')

    # ── Utfall ───────────────────────────────────────────────────────

    def test_cron_run_crashes_on_this_edition(self):
        """KÄND DEFEKT 3: ``cron_run`` söker på ett fält som inte finns.

        ``cron_run`` frågar på ``calendar_event_id.start`` /
        ``calendar_event_id.stop``. ``calendar_event_id`` är inget fält på
        ``slide.mail`` — det finns bara i en utkommenterad rad i modellen.
        Sökningen kastar därför ValueError ("Invalid field") på 18.0/19.0.

        På 20.0 grenar ``# #if`` bort de två villkoren och sökningen går
        igenom. Det betyder att cron:en är trasig på 18.0/19.0 och att
        porteringen inte upptäckte det — grinden mäter expansion, inte
        körning.

        Testet bevisar defekten; det ska fällas när ``cron_run`` rättas.
        """
        self._make_mail(
            interval_type='before_event',
            interval_unit='days',
            interval_nbr=1,
            tmp_start_date=fields.Date.today() - timedelta(days=1),
        )
        if release.version_info[0] >= 20:
            with patch.object(type(self.SlideMail), '_send_mail'):
                self.SlideMail.cron_run()
        else:
            with self.assertRaises(ValueError):
                self.SlideMail.cron_run()

    def test_cron_run_query_does_not_use_a_missing_field(self):
        """Rotorsaken till känd defekt 3, uttryckt direkt.

        ``calendar_event_id`` ska inte vara ett fält på ``slide.mail`` —
        om någon lägger till det (eller tar bort sökningen) ska det synas.
        """
        self.assertNotIn('calendar_event_id', self.SlideMail._fields)

    def test_registration_does_not_create_a_mail(self):
        """KÄND DEFEKT 4: registrering skapar ingen ``slide.mail``.

        ``slide.channel.partner.create`` loopar över ``self`` — som är en
        TOM recordset vid create, inte över de nyskapade raderna. Loopen
        körs alltså noll varv och inget mail skapas. Rätt mål är
        ``slide_channel_partner_ids``.

        Defekten finns på alla tre utgåvor. Testet bevisar den och ska
        fällas när loopen rättas.
        """
        registration = self.env['slide.channel.partner'].create({
            'channel_id': self.channel.id,
            'partner_id': self.partner.id,
        })
        self.assertTrue(registration)

        created = self.SlideMail.search([
            ('slide_channel_id', '=', self.channel.id),
            ('partner_id', '=', self.partner.id),
        ])
        self.assertFalse(created)

    def test_registration_hook_targets_the_new_records(self):
        """Rotorsaken till känd defekt 4: loopen går över ``self``.

        ``self`` är tom vid ``create``, så kroppen körs aldrig. Detta test
        läser källkoden — det är enda sättet att skilja "inget mail ska
        skapas" från "loopen kör aldrig".
        """
        import inspect

        from odoo.addons.website_slides_mail.models.slide_channel_partner import (
            SlideChannelPartner,
        )
        source = inspect.getsource(SlideChannelPartner.create)
        self.assertIn('for partner_id in self:', source)
        self.assertNotIn('for partner_id in slide_channel_partner_ids:', source)
