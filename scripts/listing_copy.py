"""Check the five Amazon.com copy fields and map clean copy to ZYing ERP."""
import json
import re
import unicodedata


FIELDS = ('product_title', 'product_highlight', 'bullet_points', 'product_description', 'backend_search_terms')
ERP_FIELDS = ('产品标题', '短标题', '要点说明', '产品描述', '关键词')
LISTING_STATES = ('COPY', 'COPY WITH OMISSIONS', 'IMAGE PENDING', 'CATEGORY CHECK', 'HOLD')
AUDIT = re.compile(r'\b(?:evidence|unverified|research|internal|omitted|conflict|seller[ -]confirmed)\b', re.I)
AFFILIATION = re.compile(
    r'\b(?:oem|oes|genuine|official|original equipment|factory (?:original|direct|replacement)|'
    r'(?:manufacturer|factory)[ -](?:approved|authori[sz]ed)|authori[sz]ed (?:dealer|distributor|replacement|product))\b',
    re.I,
)
REMINDER = re.compile(r'\b(?:verify|confirm|check)\b', re.I)
SOURCE_OR_MARKUP = re.compile(r'https?://|www\.|</?[a-z][^<>]*>|[\u3400-\u9fff？]|\?|```', re.I)


class ListingCopyError(ValueError):
    pass


def words_only(value):
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKC', value).casefold()))


def brand_issues(value, blocked):
    words = words_only(value)
    issues = []
    if AFFILIATION.search(words):
        issues.append('brand_affiliation_language')
    if any(f' {brand} ' in f' {words} ' for brand in blocked):
        issues.append('blocked_brand')
    return issues


def load_copy(path):
    if path.stat().st_size > 250_000:
        raise ListingCopyError('Listing copy input exceeds 250 KB')
    try:
        draft = json.loads(path.read_text(encoding='utf-8-sig'))
    except (ValueError, RecursionError):
        raise ListingCopyError('Provide a valid listing copy JSON object') from None
    if not isinstance(draft, dict):
        raise ListingCopyError('Provide a listing copy JSON object')
    copy = {}
    for field in FIELDS:
        value = draft.get(field)
        if field == 'bullet_points':
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                raise ListingCopyError('bullet_points must be an array of strings')
            copy[field] = [item.strip() for item in value]
        elif not isinstance(value, str):
            raise ListingCopyError(f'{field} must be a string')
        else:
            copy[field] = value.strip()
    source_brands = draft.get('blocked_brands', [])
    if not isinstance(source_brands, list) or any(not isinstance(brand, str) for brand in source_brands):
        raise ListingCopyError('blocked_brands must be an array of strings')
    status = draft.get('status')
    if status is not None and status not in LISTING_STATES:
        raise ListingCopyError('Use a recognized listing status')
    return copy, source_brands, status


def copy_issues(copy, blocked):
    issues = {}
    title, highlight, bullets, description, search = (copy[key] for key in FIELDS)
    if len(title) > 75:
        issues['product_title'] = ['over_75_characters']
    if len(highlight) > 125:
        issues['product_highlight'] = ['over_125_characters']
    if len(search.encode('utf-8')) > 249:
        issues['backend_search_terms'] = ['over_249_utf8_bytes']
    if len(bullets) != 5:
        issues['bullet_points'] = ['expected_five_bullets']

    for field, value in copy.items():
        lines = value if field == 'bullet_points' else [value]
        flags = issues.get(field, [])
        for line in lines:
            normalized = unicodedata.normalize('NFKC', line)
            if field != 'backend_search_terms' and not line:
                flags.append('empty_field_or_bullet')
            if field != 'product_description' and ('\n' in line or '\r' in line):
                flags.append('unexpected_line_break')
            if AUDIT.search(normalized) or re.search(r'\bHOLD\b', normalized):
                flags.append('internal_audit_language')
            if SOURCE_OR_MARKUP.search(normalized):
                flags.append('source_link_markup_or_non_english_copy')
            flags.extend(brand_issues(normalized, blocked))
        if flags:
            issues[field] = list(dict.fromkeys(flags))
    reminder_count = len(REMINDER.findall('\n'.join((title, highlight, *bullets, description, search))))
    if reminder_count > 1:
        issues['all_copy'] = ['repeated_purchase_reminders']
    return issues


def check_copy(path, blocked_brands, include_erp=False):
    copy, source_brands, status = load_copy(path)
    blocked = {words_only(brand) for brand in [*source_brands, *blocked_brands]} - {''}
    issues = copy_issues(copy, blocked)
    result = {
        'copy_checks_pass': not issues, 'brands_checked': len(blocked),
        'title_characters': len(copy['product_title']), 'highlight_characters': len(copy['product_highlight']),
        'bullet_characters': [len(bullet) for bullet in copy['bullet_points'][:10]],
        'description_words': len(re.findall(r"\b[\w]+(?:[-'][\w]+)*\b", copy['product_description'])),
        'backend_utf8_bytes': len(copy['backend_search_terms'].encode('utf-8')), 'issues': issues,
    }
    if status is not None:
        result['listing_status'] = status
    if include_erp and status == 'HOLD':
        result['erp_fields_blocked'] = 'HOLD'
    elif include_erp and not issues:
        result['erp_fields'] = {label: '\n'.join(copy[key]) if key == 'bullet_points' else copy[key]
                                for label, key in zip(ERP_FIELDS, FIELDS)}
    return result
