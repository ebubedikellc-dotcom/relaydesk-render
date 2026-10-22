import asyncio
from datetime import datetime, timezone, timedelta
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'RelayDesk-Main-Site-Server-v1.0.1'))
from telethon.tl.types import MessageEntityTextUrl
from telethon.extensions import html
from app.post_format import format_post, expand_links, combine_messages

STAMP = datetime(2026, 10, 22, 7, 55, tzinfo=timezone.utc)  # 8:55 WAT
LINK1 = 'https://stake.com/sports/home?iid=sport%3A674761481&source=link_shared&modal=bet'
LINK2 = 'https://stake.com/sports/home?iid=sport%3A674761233&source=link_shared&modal=bet'
FOOTBALL = f'''Combo banker on Stake
STAKE HIGH!
Play and win 1.3 million
Bet code > 674761481
Bet link {LINK1}
Bet code 2 > 674761233
Bet link 2 {LINK2}
Create an Account on STAKE
https://stake.com/?offer=bobbybetzzz&c=acugq4cK
Use Promo code BOBBYBETZZZ
To get 500k bonus
How to deposit on stake SETUP'''
CRASH = '''CRASH SIGNAL 2
Get in at > 9:10 am
Cashout at > 1.30 odds
Stake high on this
Create an Account on STAKE
https://stake.com/?offer=bobbybetzzz&c=acugq4cK
Use Promo code BOBBYBETZZZ to get 500k on deposit'''


def plain(result):
    return '\n'.join(html.parse(c)[0] for c in result.cards)


class FormattingTests(unittest.TestCase):
    def test_two_codes_match_links_and_remove_ads(self):
        r = format_post(FOOTBALL)
        self.assertEqual(r.action, 'formatted')
        self.assertEqual(len(r.cards), 1)
        for x in ('FOOTBALL', 'STAKE HIGH', '674761481', '674761233'):
            self.assertIn(x, plain(r))
        entities = html.parse(r.cards[0])[1]
        self.assertEqual([e.url for e in entities if isinstance(e, MessageEntityTextUrl)], [LINK1, LINK2])
        self.assertTrue(any(type(e).__name__ == 'MessageEntityBlockquote' for e in entities))
        for x in ('BOBBYBETZZZ', 'offer=', '1.3 million', '500k', 'YOURCODE', 'SETUP'):
            self.assertNotIn(x, r.cards[0])

    def test_only_owner_promo_for_matching_platform(self):
        opts = {'promo_code': 'OWNERCODE', 'crash_promo_code': 'CRASHCODE'}
        self.assertIn('OWNERCODE', plain(format_post(FOOTBALL, opts)))
        r = format_post(CRASH, opts, STAMP, STAMP)
        self.assertIn('CRASHCODE', plain(r))
        self.assertNotIn('OWNERCODE', plain(r))
        self.assertNotIn('OWNERCODE', plain(format_post('Football on SportyBet\nBet code: ABC123', opts)))
        self.assertNotIn('YOURCODE', plain(format_post(FOOTBALL, {'promo_code': 'YOURCODE'})))

    def test_explicit_category_beats_default(self):
        r = format_post('Table tennis on Stake\nBet code: ABC123\nMatch time: 6:30 pm WAT')
        self.assertIn('TABLE TENNIS', plain(r))
        self.assertNotIn('FOOTBALL', plain(r))
        self.assertIn('6:30 pm WAT', plain(r))
        self.assertIn('BETTING', plain(format_post('Bet code: ABC123', {'default_sport': 'betting'})))

    def test_hidden_link_and_utf16(self):
        text = '⚽ Football on Stake\nBet code: 674761481\nOpen slip'
        off = len(text[:text.index('Open slip')].encode('utf-16-le')) // 2
        expanded = expand_links(text, [MessageEntityTextUrl(off, 9, LINK1)])
        r = format_post(expanded)
        self.assertIn(LINK1.replace('&', '&amp;'), r.cards[0])
        for entity in html.parse(r.cards[0])[1]:
            self.assertLessEqual(entity.offset + entity.length, len(plain(r).encode('utf-16-le')) // 2)

    def test_link_code_controls_pairing(self):
        r = format_post(f'Football on Stake\nBet code: 123456\nBet link {LINK1}')
        self.assertIn('123456', plain(r))
        self.assertIn('674761481', plain(r))
        self.assertTrue(any('123456' in w for w in r.warnings))
        self.assertNotIn('Open bet 1', plain(r))
        self.assertIn('Open bet 2', plain(r))

    def test_referrals_and_lookalike_hosts_not_forwarded(self):
        for url in ('https://stake.com.evil.test/sports/home?iid=sport%3A123456',
                    'https://stake.com@evil.test/sports/home?iid=sport%3A123456',
                    'https://stake.com/sports/home?iid=sport%3A123456&offer=someone',
                    'https://stake.com/?offer=someone'):
            r = format_post('Bet code: 123456\nBet link '+url)
            self.assertNotIn('<a ', r.cards[0])

    def test_all_codes_survive_long_posts_and_split(self):
        src = 'Football on Stake\n' + '\n'.join(f'Bet code: {123456000+i}\nhttps://stake.com/sports/home?iid=sport%3A{123456000+i}' for i in range(100))
        r = format_post(src)
        self.assertGreater(len(r.cards), 1)
        for i in range(100):
            self.assertIn(str(123456000+i), plain(r))
        for card in r.cards:
            self.assertLessEqual(len(html.parse(card)[0].encode('utf-16-le'))//2, 4096)

    def test_crash_time_and_multiplier_no_ads(self):
        r = format_post(CRASH, posted_at=STAMP, now=STAMP)
        self.assertEqual(r.action, 'formatted')
        for value in ('CRASH', 'Stake', '09:10 AM WAT', '2026-10-22', '1.30×'):
            self.assertIn(value, plain(r))
        self.assertNotIn('STAKE HIGH', plain(r))
        self.assertNotIn('BOBBYBETZZZ', plain(r))

    def test_expired_incomplete_and_conflicting_crash_skipped(self):
        self.assertEqual(format_post(CRASH, posted_at=STAMP, now=STAMP+timedelta(minutes=20)).action, 'skipped')
        self.assertEqual(format_post('Crash signal, get ready', posted_at=STAMP, now=STAMP).action, 'skipped')
        r = format_post(CRASH+'\nPlay in the next 12 minutes', posted_at=STAMP, now=STAMP)
        self.assertEqual(r.action, 'skipped')
        self.assertIn('conflicts', r.reason)
        self.assertEqual(format_post(CRASH.replace('1.30', '0.30'), posted_at=STAMP, now=STAMP).action, 'skipped')

    def test_unrelated_posts_keep_normal_delivery_and_ads_skip(self):
        self.assertEqual(format_post('Good morning everyone').action, 'unchanged')
        self.assertEqual(format_post('Use promo code ABC123 for a bonus').action, 'skipped')
        self.assertEqual(format_post(FOOTBALL, {'enabled': False}).action, 'unchanged')

    def test_no_platform_invented_from_stake_high(self):
        r = format_post('Football\nSTAKE HIGH\nBet code: ABC123', {'promo_code': 'OWNERCODE'})
        self.assertNotIn('Platform:', plain(r))
        self.assertNotIn('OWNERCODE', plain(r))

    def test_formatting_does_not_accept_source_html(self):
        r = format_post('Football on Stake\nBet code: ABC123\n<script>alert(1)</script>')
        self.assertNotIn('<script>', r.cards[0])


class DeliveryAndApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        from cryptography.fernet import Fernet
        os.environ['DATABASE_PATH'] = cls.temp.name+'/relay.db'
        os.environ['TEMP_DIR'] = cls.temp.name+'/tmp'
        os.environ['ADMIN_PASSWORD'] = 'local-test-only'
        os.environ['FERNET_KEY'] = Fernet.generate_key().decode()
        from app import store
        from app.telegram_service import RelayEngine
        from app.main import app
        from fastapi.testclient import TestClient
        cls.store, cls.Engine = store, RelayEngine
        store.init_db()
        cls.relay_id = store.save_relay({'name':'Test','source_link':'source','destination_link':'target'})
        cls.relay = store.get_relay(cls.relay_id)
        cls.client = TestClient(app)  # No lifespan: never connects to Telegram.

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.temp.cleanup()

    def setUp(self):
        from app.post_format import DEFAULTS
        self.store.save_post_format_settings(dict(DEFAULTS))

    def message(self, number, text, media=None):
        return SimpleNamespace(id=number, chat_id=1, date=datetime.now(timezone.utc), message=text, entities=[],
                               media=media, photo=None, voice=None, video=None, video_note=None, document=None,
                               download_media=AsyncMock(return_value=None))

    def engine(self):
        engine = self.Engine()
        engine.client = SimpleNamespace(get_entity=AsyncMock(return_value='target'),
                                        send_message=AsyncMock(return_value=SimpleNamespace(id=99)),
                                        send_file=AsyncMock(return_value=SimpleNamespace(id=100)))
        return engine

    def test_actual_delivery_uses_cards_and_suppresses_duplicate(self):
        e = self.engine();m = self.message(101, FOOTBALL)
        self.assertTrue(asyncio.run(e._deliver(self.relay, [m])))
        self.assertTrue(asyncio.run(e._deliver(self.relay, [m])))
        self.assertEqual(e.client.send_message.await_count, 1)
        sent = e.client.send_message.call_args
        self.assertIn('FOOTBALL', sent.args[1])
        self.assertNotIn('BOBBYBETZZZ', sent.args[1])
        self.assertFalse(sent.kwargs['link_preview'])

    def test_expired_crash_not_sent_or_retried(self):
        e = self.engine();m = self.message(102, CRASH);m.date=STAMP
        with patch('app.post_format.datetime') as dt:
            dt.now.return_value = STAMP + timedelta(days=1)
            dt.side_effect = datetime
            dt.strptime = datetime.strptime
            self.assertTrue(asyncio.run(e._deliver(self.relay, [m])))
        e.client.send_message.assert_not_awaited()
        self.assertTrue(self.store.delivery_exists(self.relay_id, 102))
        self.assertEqual(self.store.recent_deliveries(1)[0]['status'], 'skipped')

    def test_album_preserves_media_removes_original_captions_and_cleans_files(self):
        e = self.engine();messages = [self.message(103, FOOTBALL, object()), self.message(104, '', object())]
        for i,m in enumerate(messages):
            async def download(file, number=i):
                path = Path(file)/(str(number)+'.jpg');path.write_bytes(b'local fixture');return str(path)
            m.download_media = AsyncMock(side_effect=download)
        self.assertTrue(asyncio.run(e._deliver(self.relay, messages)))
        self.assertEqual(e.client.send_file.call_args.kwargs['caption'], ['', ''])
        self.assertEqual(e.client.send_message.await_count, 1)
        self.assertEqual(list(Path(os.environ['TEMP_DIR']).iterdir()), [])

    def test_settings_authenticated_persistent_and_preview_sends_nothing(self):
        self.assertEqual(self.client.get('/api/post-format').status_code, 401)
        auth=('admin','local-test-only')
        settings = self.client.get('/api/post-format', auth=auth).json()['settings']
        settings['promo_code']='OWNER123'
        self.assertEqual(self.client.put('/api/post-format', auth=auth, json=settings).status_code, 200)
        self.assertEqual(self.store.post_format_settings()['promo_code'], 'OWNER123')
        r = self.client.post('/api/post-format/preview', auth=auth, json={'text':FOOTBALL})
        self.assertEqual(r.status_code, 200)
        self.assertIn('OWNER123', r.json()['cards'][0]['text'])
        for field,value in [('promo_code','YOURCODE'),('promo_code','<script>'),('source_timezone','NoSuch/Timezone')]:
            invalid={**settings,field:value}
            self.assertEqual(self.client.put('/api/post-format', auth=auth, json=invalid).status_code, 422)
        self.assertEqual(self.client.post('/api/post-format/preview', auth=auth, json={'text':CRASH,'posted_at':'2026-10-22T08:55:00'}).status_code, 422)


if __name__ == '__main__':
    unittest.main()
