"""Official Rules, Free Entry, Privacy, Terms, Contact and Winner pages, plus the printable mail-in form.

Everything is generated from the campaign settings. Any value the organization has not verified yet is
rendered as a placeholder ("[[Label]]"), which the site highlights and the PDF prints as a blank to fill in.
These are drafts for counsel: nothing here claims that any approval has been obtained.
"""
import re
from datetime import datetime

import raffle_core as core

NPN = ('NO PURCHASE OR DONATION NECESSARY TO ENTER OR WIN. Making a contribution will not improve your odds of winning. '
       'Eligible free entries and donation-based entries receive equal treatment. Void where prohibited.')

DOCS = {'rules': 'Official Rules', 'free-entry': 'Free Entry Instructions', 'privacy': 'Privacy Policy',
        'terms': 'Terms and Conditions', 'contact': 'Contact Us', 'winners': 'Winner Information'}


def ph(value, label):
    v = str(value or '').strip()
    return v if v else f'[[{label}]]'


def fmt_dt(v):
    try:
        return datetime.fromisoformat(v).strftime('%B %-d, %Y at %-I:%M %p') + ' Eastern Time'
    except (TypeError, ValueError):
        return ''


def context(camp, info, site_url=''):
    unit, n = info['unit_price_cents'], info['max_tickets']
    return dict(
        org=ph(camp.get('org_legal_name'), 'Organization full legal name'),
        status=ph(camp.get('org_nonprofit_status'), 'Nonprofit status, once verified'),
        ein=ph(camp.get('org_ein'), 'Federal EIN'),
        addr=ph(camp.get('org_address'), 'Physical mailing address'),
        email=ph(camp.get('org_email'), 'Contact email'),
        phone=ph(camp.get('org_phone'), 'Contact telephone'),
        purpose=ph(camp.get('campaign_purpose'), 'Purpose of the fundraising campaign'),
        number=ph(camp.get('campaign_number'), 'Campaign identification number'),
        title=camp['title'], n=n, min=core.money(unit), max=core.money(unit * n), unit=core.money(unit),
        start=fmt_dt(camp.get('start_at')) or '[[Opening date and time]]',
        end=fmt_dt(camp.get('end_at')) or '[[Entry deadline (date and time)]]',
        drawing=ph(camp.get('drawing_date'), 'Drawing date and time'),
        method=ph(camp.get('drawing_method'), 'Drawing procedure, e.g. conducted live and in public view, and where it can be watched'),
        age=int(camp.get('min_age') or 18),
        regions=ph(camp.get('eligible_regions'), 'Eligible states/countries, as approved by counsel'),
        county=ph(camp.get('governing_county'), 'County'),
        arv=ph(camp.get('prize_arv'), 'Total approximate retail value of the prize'),
        winners=int(camp.get('winners') or 1), claim=int(camp.get('claim_days') or 14),
        site=site_url or '[[Website address]]', free=bool(camp.get('free_entry_enabled')),
    )


def custom(text):
    """Admin-supplied replacement text: blank lines separate paragraphs; a line starting with '#' is a heading."""
    sections, cur = [], {'h': '', 'p': []}
    for block in re.split(r'\n\s*\n', text.strip()):
        block = block.strip()
        if block.startswith('#'):
            head, _, rest = block.partition('\n')
            if cur['h'] or cur['p']:
                sections.append(cur)
            cur = {'h': head.lstrip('# ').strip(), 'p': [rest.strip()] if rest.strip() else []}
        elif block:
            cur['p'].append(block)
    if cur['h'] or cur['p']:
        sections.append(cur)
    return sections


def free_entry_steps(x):
    return [
        f'To enter without making a donation, hand-print the following on the official mail-in entry form (download below) or on a plain '
        f'sheet of paper: your first and last name, complete street address, city, state, ZIP code, country, email address, telephone '
        f'number, and the campaign identification number ({x["number"]}). Sign and date it to confirm that you are eligible and agree to the '
        f'Official Rules.',
        f'Mail it in a stamped envelope to: {x["org"]}, Attn: {x["title"]} Free Entry, {x["addr"]}.',
        f'Mail-in entries must be received during the Entry Period: by {x["end"]}, or before all {x["n"]} entries have been issued, '
        f'whichever comes first. Entries can fill before the deadline, so mail early. One entry per envelope.',
        'Each eligible free entry is assigned a random, unused entry number from the same pool as donation entries and confirmed by email. '
        'Free entries and donation entries are placed in the same drawing and are treated equally.',
        'Entries that are incomplete, illegible, late, mechanically reproduced, or missing the campaign identification number are void.',
    ]


def rules_sections(camp, x):
    lim = int(camp.get('entries_per_person') or 0)
    limit = (f'Limit: {lim} entr{"y" if lim == 1 else "ies"} per person for this campaign, regardless of entry method.' if lim else
             f'There is no per-person limit other than the {x["n"]}-entry maximum; each free entry must be mailed separately.')
    prize_lines = ' '.join(f'{i}' for i in camp.get('prize_items') or [])
    rest = ', '.join(r['name'] for r in camp.get('restaurants') or [])
    exclusions = camp.get('exclusions') or (
        'Employees, officers, directors and volunteers of the Sponsor who are involved in administering the Giveaway, and their '
        'immediate family members (spouse, parents, children, siblings) and household members, are not eligible.')
    free = x['free']
    return [
        {'h': '1. Sponsor', 'p': [
            f'This charitable fundraising giveaway (the "Giveaway"), campaign identification number {x["number"]}, is sponsored and '
            f'administered by {x["org"]}, {x["status"]} (the "Sponsor"), {x["addr"]}. Federal EIN: {x["ein"]}. '
            f'Questions: {x["email"]} or {x["phone"]}.',
            f'Purpose of the campaign: {x["purpose"]}']},
        {'h': '2. Free Entry', 'p': [
            'No purchase, payment, donation or contribution is necessary to enter or win, and a contribution will not improve your '
            'chances of winning. There are two ways to enter. All eligible entries, whether or not accompanied by a contribution, are '
            'placed in the same drawing and are treated equally. See Section 5(b) and the Free Entry Instructions.'] if free else [
            '[[No free method of entry is enabled. Counsel must confirm the campaign structure before publication.]]']},
        {'h': '3. Eligibility', 'p': [
            f'The Giveaway is open only to legal residents of {x["regions"]} who are at least {x["age"]} years old (or the age of '
            f'majority where they live, if higher) on the date of entry.', exclusions,
            'Void where prohibited or restricted by law. By entering, each entrant agrees to these Official Rules and to the decisions of '
            'the Sponsor, which are final on all matters relating to the Giveaway.']},
        {'h': '4. Campaign Period', 'p': [
            f'Entries open on {x["start"]} and close on {x["end"]}, or as soon as all {x["n"]} entries have been issued, whichever comes '
            f'first (the "Entry Period"). All times are Eastern Time, and the Sponsor\'s server clock is the official timekeeper.',
            f'If all {x["n"]} entries are issued before the scheduled deadline, entries close immediately for both entry methods, and '
            f'the drawing still takes place on {x["drawing"]}.']},
        {'h': '5. Entry Methods', 'p': [
            f'(a) Donation entry. Visit {x["site"]}, provide your name, email address and telephone number, review and accept the payment '
            f'authorization, and spin. The system assigns a random, unused entry number from 1 to {x["n"]}. Your donation amount equals '
            f'your entry number multiplied by {x["unit"]}, so it is between {x["min"]} and {x["max"]}. The range is shown before you authorize '
            f'payment, and the exact amount is shown as soon as your number is assigned. The amount does not affect your chance of winning.',
            ('(b) Free entry. ' + ' '.join(free_entry_steps(x))) if free else '(b) [[Free entry method to be confirmed by counsel.]]',
            limit,
            'Duplicate entries beyond the limit, and incomplete, illegible, late, automated, mechanically reproduced, bulk or fraudulent '
            'entries, are void. Using multiple email addresses, identities or devices to get around the limit voids all of that '
            'person\'s entries. Entries are processed in the order received. Proof of sending is not proof of receipt.']},
        {'h': '6. Maximum Entries', 'p': [
            f'The Giveaway is limited to {x["n"]} entries. Each entry receives a unique number from 1 to {x["n"]}, and the system '
            f'prevents any number from being issued twice, including during simultaneous submissions. Once all {x["n"]} entries are '
            f'issued, no further entries are accepted by either method, and the Sponsor will post a notice on the website.',
            'Numbers of refunded or disqualified entries are not reissued. A number reserved for a donation that could not be completed may '
            'be returned to the pool.']},
        {'h': '7. Winning Odds', 'p': [
            f'The odds of winning depend on the number of eligible entries received and the number of prizes ({x["winners"]}). If all '
            f'{x["n"]} entries are issued and eligible, the odds of winning are {x["winners"]} in {x["n"]}. A contribution does not change '
            f'the odds of winning.']},
        {'h': '8. Winner Selection and Notification', 'p': [
            f'On {x["drawing"]}, the Sponsor will select {x["winners"]} winner{"s" if x["winners"] > 1 else ""} at random from all '
            f'eligible entries. Drawing procedure: {x["method"]}.',
            f'The Sponsor will notify the potential winner by telephone and email using the contact information provided at entry. The '
            f'potential winner must respond within {x["claim"]} days of the first notification attempt and may be required to sign an '
            f'affidavit of eligibility, a liability release and, where lawful, a publicity release, and to provide a completed IRS Form '
            f'W-9, before the prize is awarded.',
            'If the potential winner cannot be reached, a prize notification is returned as undeliverable, the potential winner is found '
            'ineligible, declines the prize, or does not return the required documents on time, the prize is forfeited and an alternate '
            'winner is selected at random from the remaining eligible entries.']},
        {'h': '9. Prize Details', 'p': [
            f'Prize: {prize_lines}', f'Participating restaurants: {rest}.' if rest else '',
            f'Approximate retail value (ARV): {x["arv"]}.',
            ph(camp.get('prize_terms'), 'Gift card conditions: issuer, face values, expiration dates, reservation requirements, '
               'transportation credit terms and geographic limits'),
            'The prize is not transferable and cannot be redeemed for cash. No substitution is permitted, except that the Sponsor may '
            'substitute a prize of equal or greater value if any part of the prize becomes unavailable. Gift cards are subject to the '
            'terms of their issuers.',
            ph(camp.get('prize_source'), 'Source of the prizes (donated or purchased)'),
            'The participating restaurants and Uber are not sponsors of the Giveaway and do not endorse or administer it. Their names '
            'identify where the prize gift cards can be used.']},
        {'h': '10. Taxes', 'p': [
            'The winner is solely responsible for all federal, state and local taxes on the prize. If the value of the prize is $600 or '
            'more, the Sponsor will report it to the IRS as required, and the winner must provide a completed IRS Form W-9 (including a '
            'valid Social Security or taxpayer identification number) before the prize is released. The winner should consult a tax adviser.',
            'Contributions made in connection with the Giveaway may not be tax-deductible. Consult your tax adviser.']},
        {'h': '11. Publicity', 'p': [
            'Where permitted by law, accepting the prize constitutes the winner\'s consent to the Sponsor publishing the winner\'s name, '
            'city and state of residence, and the winning entry number in announcements of the result. Photographs or statements of the '
            'winner are used only with the winner\'s separate permission.',
            'The winner may instead ask to be announced as "Anonymous," where permitted by law. The winning entry number is always '
            'published.' if camp.get('winner_anonymous_allowed') else '']},
        {'h': '12. General Conditions', 'p': [
            'The Sponsor may disqualify anyone it finds tampering with the entry process or the operation of the Giveaway, submitting '
            'duplicate entries beyond the limit, providing false information about identity, address, telephone number or email '
            'address, or otherwise violating these Official Rules. The Sponsor interprets these Official Rules, and its decisions are '
            'final.',
            'If fraud, technical failure or any other cause beyond the Sponsor\'s reasonable control impairs the integrity or proper conduct '
            'of the Giveaway, the Sponsor may, where permitted by law, modify, suspend or cancel it. Any modification will be posted on the '
            'website and will not reduce the prize or change the odds for entries already received.',
            'If the Giveaway is cancelled before the drawing, donations made for entries will be refunded to the original payment method. '
            'Otherwise, donations are refunded only as the Sponsor determines in its discretion or as required by law.',
            'If any provision of these Official Rules is held invalid or unenforceable, the remaining provisions stay in full force and '
            'effect.']},
        {'h': '13. Limitation of Liability', 'p': [
            'By entering, each entrant releases and holds harmless the Sponsor and its officers, directors, volunteers and agents from any '
            'liability, injury, loss or damage arising from participation in the Giveaway or from accepting, possessing or using the prize. '
            'Restaurant meals and services are provided by the restaurants, and transportation is provided by Uber and its drivers; the '
            'Sponsor is not responsible for their services, availability, reservations, closures or conduct. The Sponsor is not '
            'responsible for lost, late, misdirected, illegible or postage-due mail, or for technical or human errors in entry or '
            'administration.']},
        {'h': '14. Governing Law and Disputes', 'p': [
            f'These Official Rules are governed by the laws of the State of New York, without regard to its conflict-of-law principles. '
            f'Any dispute arising from the Giveaway will be resolved exclusively in the state or federal courts located in {x["county"]} '
            f'County, New York.']},
        {'h': '15. Privacy', 'p': [
            'Information collected from entrants is used to administer the Giveaway, process donations, contact entrants about their '
            'entries, and comply with law. Marketing messages are sent only to entrants who separately opt in. The Sponsor does not sell '
            'entrant information. See the Privacy Policy for details.']},
        {'h': '16. Winner Information', 'p': [
            f'The result is posted on the Winner Information page at {x["site"]} after the drawing. For the winner\'s name, email '
            f'{x["email"]} or send a self-addressed stamped envelope to {x["org"]}, {x["addr"]}, within 60 days after the drawing.']},
    ]


def privacy_sections(camp, x):
    return [
        {'h': 'What we collect', 'p': [
            'For donation entries: your name, email address and telephone number, the entry number and amount, consent records (the text you '
            'agreed to, the time, and the rules version), and payment references from our processor. Card details are entered directly into '
            'Stripe\'s secure form and are never seen or stored by us.',
            'For mail-in entries: the information on the form, including your mailing address.',
            'Technical information such as IP address and browser type may be recorded in server logs for security.']},
        {'h': 'How we use it', 'p': [
            'To administer the Giveaway: issue entry numbers, process and record donations, send confirmations, conduct the drawing, verify '
            'eligibility, contact and award the winner, prevent fraud, keep required records, and comply with law.',
            'Marketing is separate and optional. We email you about future events and fundraisers only if you tick the optional marketing '
            'box, and you can unsubscribe at any time. Entering the Giveaway does not require marketing consent.']},
        {'h': 'Who we share it with', 'p': [
            'Stripe, to process payments; our email provider, to send confirmations; and regulators, auditors or others when required by '
            'law. We do not sell or rent your information. The winner\'s name may be published as described in the Official Rules.']},
        {'h': 'How long we keep it', 'p': [
            ph(camp.get('privacy_retention'), 'Retention period: how long entry, payment and consent records are kept (for example, as '
               'required by charitable-gaming and tax record-keeping rules)')]},
        {'h': 'Your choices', 'p': [
            f'To update or delete your information, or to stop marketing messages, contact {x["email"]} or {x["phone"]}. We may keep '
            f'records we are legally required to retain.']},
        {'h': 'Contact', 'p': [f'{x["org"]}, {x["addr"]}. {x["email"]} · {x["phone"]}.']},
    ]


def terms_sections(camp, x):
    return [
        {'h': 'About this website', 'p': [
            f'This website is operated by {x["org"]} to run the {x["title"]} charitable fundraising giveaway. Participation is governed '
            f'by the Official Rules, which control if they conflict with these terms.']},
        {'h': 'Payments', 'p': [
            'Donations are processed by Stripe. Before you authorize a payment, the website shows the range of possible amounts; you are '
            'charged only the amount of the entry number assigned to you. Card details go directly to Stripe and are not stored by us.',
            'Contributions may not be tax-deductible. Consult your tax adviser.']},
        {'h': 'Acceptable use', 'p': [
            'Do not use automated tools, scripts or bulk submissions, interfere with the website, or submit false information. We may '
            'void entries and block access for violations.']},
        {'h': 'Third-party names', 'p': [
            'Restaurant and Uber names, logos and photographs identify where the prize gift cards can be used. Those businesses are not '
            'sponsors of the Giveaway and do not endorse or administer it.']},
        {'h': 'Disclaimers', 'p': [
            'The website is provided "as is." To the extent permitted by law, the Sponsor is not liable for interruptions, errors or '
            'technical failures.']},
        {'h': 'Governing law', 'p': [f'These terms are governed by the laws of the State of New York. Disputes will be resolved in the '
                                     f'state or federal courts located in {x["county"]} County, New York.']},
    ]


def contact_sections(camp, x):
    return [
        {'h': 'Organization', 'p': [x['org'], x['status'], f'Federal EIN: {x["ein"]}']},
        {'h': 'Mailing address', 'p': [x['addr']]},
        {'h': 'Email and telephone', 'p': [f'{x["email"]} · {x["phone"]}']},
        {'h': 'Purpose of this campaign', 'p': [x['purpose']]},
    ]


def winners_sections(camp, x, drawing):
    if drawing and drawing.get('drawn_at'):
        nums = ', '.join(f'#{n}' for n in drawing['winners'])
        p = [f'The drawing took place on {drawing["drawn_at"]} UTC. Winning entry number{"s" if len(drawing["winners"]) > 1 else ""}: {nums}.']
        if camp.get('winner_info'):
            p.append(camp['winner_info'])
        p.append('Verification data for the drawing is published at /api/drawing.')
    else:
        p = [f'The drawing has not taken place yet. It is scheduled for {x["drawing"]}. The result will be posted here.']
    p.append(f'You can also request the winner\'s name by emailing {x["email"]} or by sending a self-addressed stamped envelope to '
             f'{x["org"]}, {x["addr"]}, within 60 days after the drawing.')
    return [{'h': 'Result', 'p': p}]


def build(camp, info, drawing=None, site_url=''):
    x = context(camp, info, site_url)
    approved = camp.get('legal_approval_status') == 'approved'
    overrides = {'rules': 'official_rules', 'free-entry': 'free_entry_instructions', 'privacy': 'privacy_policy', 'terms': 'terms_text'}
    gen = {
        'rules': lambda: rules_sections(camp, x),
        'free-entry': lambda: [{'h': 'How to enter for free', 'p': free_entry_steps(x)}] if x['free'] else
            [{'h': 'Free entry', 'p': ['[[Free entry is not enabled. Counsel must confirm the campaign structure before publication.]]']}],
        'privacy': lambda: privacy_sections(camp, x),
        'terms': lambda: terms_sections(camp, x),
        'contact': lambda: contact_sections(camp, x),
        'winners': lambda: winners_sections(camp, x, drawing),
    }
    docs = {}
    for slug, title in DOCS.items():
        key = overrides.get(slug)
        sections = custom(camp[key]) if key and (camp.get(key) or '').strip() else gen[slug]()
        for s in sections:
            s['p'] = [p for p in s['p'] if p]
        docs[slug] = {'title': title, 'sections': sections}
    return {'docs': docs, 'npn': NPN if x['free'] else '', 'draft': not approved,
            'rules_version': camp.get('rules_version') or '', 'org': {k: x[k] for k in ('org', 'status', 'ein', 'addr', 'email', 'phone')},
            'campaign_number': x['number'], 'title': camp['title'], 'free_entry_enabled': x['free']}


# ───────────────────────────── printable mail-in form (PDF) ─────────────────────────────

def _latin(s):
    s = str(s).replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"') \
        .replace('–', '-').replace('—', '-').replace('…', '...').replace(' ', ' ')
    return re.sub(r'\[\[[^\]]*\]\]', '________________', s).encode('latin-1', 'replace').decode('latin-1')


def free_entry_pdf(camp, info):
    from fpdf import FPDF
    x = context(camp, info)
    gold, ink, muted = (168, 128, 54), (20, 22, 30), (110, 110, 120)
    pdf = FPDF(format='Letter', unit='pt')
    pdf.set_auto_page_break(False)
    pdf.add_page()
    W, M = 612, 48
    pdf.set_fill_color(*ink)
    pdf.rect(M, 40, W - 2 * M, 78, 'F')
    pdf.set_text_color(*gold)
    pdf.set_font('Helvetica', '', 9)
    pdf.set_xy(M, 52)
    pdf.cell(W - 2 * M, 12, _latin(camp.get('presents') or '').upper(), align='C')
    pdf.set_text_color(255, 255, 255)
    pdf.set_font('Times', 'B', 24)
    pdf.set_xy(M, 68)
    pdf.cell(W - 2 * M, 28, _latin(x['org'] if not x['org'].startswith('[[') else camp['org_name']), align='C')
    pdf.set_font('Helvetica', '', 9)
    pdf.set_xy(M, 98)
    pdf.cell(W - 2 * M, 12, _latin(camp['title']).upper(), align='C')

    pdf.set_text_color(*ink)
    pdf.set_font('Times', 'B', 22)
    pdf.set_xy(M, 134)
    pdf.cell(W - 2 * M, 26, 'FREE MAIL-IN ENTRY FORM', align='C')
    if not camp.get('legal_approval_status') == 'approved':
        pdf.set_text_color(190, 60, 40)
        pdf.set_font('Helvetica', 'B', 8)
        pdf.set_xy(M, 160)
        pdf.cell(W - 2 * M, 10, 'DRAFT - PENDING LEGAL REVIEW - NOT FOR DISTRIBUTION', align='C')
        pdf.set_text_color(*ink)

    y = 178
    pdf.set_draw_color(*gold)
    pdf.set_fill_color(248, 245, 238)
    pdf.rect(M, y, W - 2 * M, 50, 'DF')
    pdf.set_xy(M + 12, y + 8)
    pdf.set_font('Helvetica', 'B', 9)
    pdf.multi_cell(W - 2 * M - 24, 11, _latin(NPN), align='C')

    y = 240
    pdf.set_font('Helvetica', '', 9)
    pdf.set_xy(M, y)
    pdf.multi_cell(W - 2 * M, 12, _latin(
        f'Open to legal residents of {x["regions"]}, age {x["age"]}+. Print this form, complete every field in ink, sign it, and mail '
        f'it to the address below. One entry per envelope. Entries must be received by {x["end"]}, or before all {x["n"]} entries '
        f'have been issued, whichever comes first.'), align='C')

    y = 290
    pdf.set_draw_color(*ink)
    pdf.set_line_width(1.2)
    pdf.rect(M, y, W - 2 * M, 44)
    pdf.set_line_width(0.6)
    pdf.set_font('Helvetica', 'B', 11)
    pdf.set_xy(M + 14, y + 10)
    pdf.cell(220, 14, 'Campaign identification number:')
    num = camp.get('campaign_number') or ''
    pdf.line(M + 232, y + 26, W - M - 14, y + 26)
    if num:
        pdf.set_xy(M + 236, y + 10)
        pdf.cell(200, 14, _latin(num))
    pdf.set_font('Helvetica', '', 7.5)
    pdf.set_xy(M + 14, y + 29)
    pdf.cell(W - 2 * M - 28, 10, 'Your entry is not valid unless the campaign identification number is written above.')

    def field(label, x0, y0, w):
        pdf.set_font('Helvetica', 'B', 7.5)
        pdf.set_text_color(*muted)
        pdf.set_xy(x0, y0)
        pdf.cell(w, 9, label)
        pdf.set_draw_color(*muted)
        pdf.line(x0, y0 + 30, x0 + w, y0 + 30)
        pdf.set_text_color(*ink)

    L, R, half = M, W / 2 + 8, W / 2 - M - 8
    y = 352
    field('FIRST NAME', L, y, half); field('LAST NAME', R, y, half); y += 42
    field('STREET ADDRESS', L, y, W - 2 * M); y += 42
    field('CITY', L, y, 220); field('STATE', L + 236, y, 120); field('ZIP CODE', L + 372, y, W - 2 * M - 372); y += 42
    field('COUNTRY', L, y, half); field('TELEPHONE', R, y, half); y += 42
    field('EMAIL ADDRESS', L, y, W - 2 * M); y += 46

    pdf.set_font('Helvetica', '', 8.5)
    pdf.set_xy(M, y)
    pdf.multi_cell(W - 2 * M, 11, _latin(
        f'I certify that I am a legal resident of {x["regions"]}, that I am at least {x["age"]} years old (or the age of majority where '
        f'I live, if higher), and that I have read and agree to the Official Rules of the {camp["title"]} giveaway '
        f'(rules version {camp.get("rules_version") or "-"}).'))
    y = pdf.get_y() + 8
    field('SIGNATURE', L, y, 340); field('DATE', L + 356, y, W - 2 * M - 356); y += 46

    pdf.set_draw_color(200, 200, 205)
    pdf.rect(M, y, W - 2 * M, 66)
    pdf.set_xy(M + 12, y + 8)
    pdf.set_font('Helvetica', 'B', 9)
    pdf.cell(300, 11, 'MAIL YOUR COMPLETED ENTRY TO:')
    pdf.set_font('Helvetica', '', 9)
    pdf.set_xy(M + 12, y + 22)
    pdf.multi_cell(W - 2 * M - 24, 11, _latin(f'{x["org"]}\nAttn: {camp["title"]} Free Entry\n{x["addr"]}'))

    pdf.set_text_color(*muted)
    pdf.set_font('Helvetica', '', 7.5)
    pdf.set_xy(M, 742)
    pdf.multi_cell(W - 2 * M, 9.5, _latin(
        f'{x["org"]} - {x["status"]} - EIN {x["ein"]}. Free entries and donation entries are placed in the same drawing and are '
        f'treated equally. Drawing: {x["drawing"]}.'), align='C')
    return bytes(pdf.output())
