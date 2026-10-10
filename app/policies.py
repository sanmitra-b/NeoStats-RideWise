import hashlib
import re
from pypdf import PdfReader

FILES = {
    'rental': '01_Rental_Agreement_and_Terms.pdf',
    'refund_v1': '02_Cancellation_and_Refund_Policy_v1.pdf',
    'refund_v2': '03_Cancellation_and_Refund_Policy_v2.pdf',
    'penalty': '04_Late_Return_and_Damage_Penalty_Schedule.pdf',
    'ev': '05_EV_User_Guide_and_FAQ.pdf',
}
HASHES = {
    'rental': '5cbd5b6e0ae95a8b16f3c5e494fdfad7654f13963b600dc27b9ceafd62f74ac1',
    'refund_v1': 'a4caf1f87ae15e674dff32721e530348461f3dd86b1474bf5a470a1bd9b71249',
    'refund_v2': 'a0f297d14458a8549380834cc65cc98ea0567ec4eb0ee2784d5b9602fccb2b15',
    'penalty': '218d597b9c5185d40bc5b2a7f8891429c68543341c1502c68ce11a6f77724bab',
    'ev': '3ca2bd886adca577a6784622529f967825df4e397f9b0a40fd98c1a8e93220cb',
}
# Reviewed transcriptions of supplied visual-only content, bound to original hashes.
VISUALS = {
    ('refund_v2', 2): 'Reviewed signed cancellation annexure: cancellation at least 48 hours before scheduled pickup: 100% refund; 12 to less than 48 hours: 75%; 2 to less than 12 hours: 25%; less than 2 hours: 0%. Apply to rental actually paid and proportionate GST. The introductory wider-window wording does not override this signed schedule.',
    ('penalty', 3): 'Reviewed tier-benefits annexure: STANDARD 0 minutes grace; SILVER 0 minutes; GOLD 30 minutes inclusive. If lateness exceeds grace, charge for the entire lateness, rounded up to begun hours. Grace is not deducted.',
    ('ev', 1): 'Reviewed charging figure: park at a hub or approved charger; switch off the vehicle; connect the RideWise cable; wait for the green light on the dashboard; unplug and stow the cable under the seat.',
    ('ev', 2): 'Reviewed battery-band figure: red below 10%: Rs 150 fee; amber 10–19%: no fee, charge before the next trip; green at least 20%: ideal return. Exactly 10% has no low-battery fee.',
}
VERSIONS = {'rental': '3.0', 'refund_v1': '1.0', 'refund_v2': '2.0', 'penalty': '2.1', 'ev': '1.4'}

class Policies:
    def __init__(self, directory):
        self.directory = directory
        self.pages = []
        self.valid = set()
        for key, filename in FILES.items():
            path = directory / filename
            if not path.exists():
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            reviewed = digest == HASHES[key]
            if reviewed:
                self.valid.add(key)
            for page, pdfpage in enumerate(PdfReader(path).pages, 1):
                text = pdfpage.extract_text() or ''
                visual = VISUALS.get((key, page)) if reviewed else None
                self.pages.append({'id': f'PDF-{key}-{page}', 'kind': 'pdf', 'key': key,
                    'filename': filename, 'page': page, 'version': VERSIONS[key], 'hash': digest,
                    'reviewed': reviewed, 'method': 'PDF text + reviewed visual transcription' if visual else 'PDF text',
                    'excerpt': text + ('\n\n' + visual if visual else ''),
                    'url': f'/api/policies/{key}#page={page}'})

    def require(self, *keys):
        if any(k not in self.valid for k in keys):
            raise ValueError('A required policy is missing or changed. Review it before calculating charges.')

    def retrieve(self, question, topic='all'):
        keys = {'rental': {'rental'}, 'refund': {'rental', 'refund_v1', 'refund_v2'},
                'penalty': {'rental', 'penalty'}, 'ev': {'ev', 'penalty'}, 'all': set(FILES)}[topic]
        tokens = set(re.findall(r'[a-z]{3,}', question.lower())) - {'what', 'which', 'the', 'and', 'can', 'for', 'how', 'does', 'with'}
        scored = sorted(((sum(t in p['excerpt'].lower() for t in tokens), p) for p in self.pages if p['key'] in keys), key=lambda x: x[0], reverse=True)
        selected = [p for score, p in scored if score > 0][:6]
        if not selected:
            selected = [p for _, p in scored][:4]
        # Keep authoritative visual annexures with the related prose.
        wanted = {p['id'] for p in selected}
        for p in self.pages:
            if (p['key'], p['page']) in VISUALS and p['key'] in keys and p['id'] not in wanted:
                selected.append(p)
        return selected

    def pages_for(self, *keys):
        return [p for p in self.pages if p['key'] in keys]
