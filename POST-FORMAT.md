# Betting post formatting

Version 1.3.0 formats live and imported message text/captions on the existing Telegram relay. It does not add X or WhatsApp connections.

The owner panel has **Post format**, persistent settings and a preview that never sends messages. Formatting is enabled by default. Unlabelled sports booking posts use the owner-selected category (initially Football); explicit Football, Table Tennis, Basketball, Tennis and Crash labels take priority. Sports posts include STAKE HIGH unless turned off.

Every extracted booking code is retained. Stake sports/home links are matched by their `iid=sport:CODE`; known bookmaker links using bookingCode/shareCode/booking_code can also be matched. Unrecognised or mismatched URLs are not guessed. See activity warnings. Promo/referral URLs are removed. Only owner-entered promo codes are added, for their matching bookmaker. Both promo fields start blank; demonstration placeholders cannot be saved.

Crash requires an entry time and a valid cash-out target. The original Telegram post date and configured source timezone (initially Africa/Lagos) supply missing date/zone information; explicit ISO dates, tomorrow, and WAT/UTC/GMT are supported. Missing, expired, conflicting or ambiguous details skip delivery and appear in activity. This does not validate or predict gambling outcomes.

Messages use Telegram blockquote cards, bold headings, selectable codes and clickable booking links. Long lists split without breaking code/link pairs. Associated media is preserved separately; text baked into images/videos is not extracted or removed. Other messages keep the existing link-removal behavior, except promo-only posts are skipped. Owner-composed messages remain unchanged.

Run: `python -m unittest discover -s tests -v` with the server requirements and httpx installed. Tests use a temporary database and mocked Telegram client; they never send a real post. JavaScript syntax: `node --check RelayDesk-Control-Panel-v1.0.1/app.js`.
