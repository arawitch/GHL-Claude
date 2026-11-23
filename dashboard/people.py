"""Counting people rather than contact records.

94.8% of contacts exist in both GoHighLevel sub-accounts, usually with the
same tags, so a tag count taken from one account understates the audience and
the sum of both roughly doubles it. Everything on the dashboard that claims to
be a number of *people* goes through here, so the same tag cannot read 106 in
one panel and 128 in another.

Identity is the email where there is one, falling back to the last ten digits
of the phone, and finally the contact id - two records for the same person
nearly always share an email, and a record with neither is its own person
rather than silently merged into someone else.
"""
import re


def norm_phone(value):
    digits = re.sub(r'\D', '', value or '')
    return digits[-10:] if len(digits) >= 10 else ''


def identity(contact):
    """One key per real person, so the two sub-accounts can be merged."""
    email = (contact.get('email') or '').strip().lower()
    if email:
        return 'e:' + email
    phone = norm_phone(contact.get('phone'))
    return ('p:' + phone) if phone else 'id:' + str(contact.get('id'))


def tagged(clients, tag):
    """Every person carrying `tag` in any of `clients`, keyed by identity.

    `clients` is a list of (account_label, GHLClient). Each person's record
    carries the union of their tags and ids across accounts, because the two
    accounts drift: a tag written by an app that only knows one account would
    otherwise be invisible when counted from the other.

    An account whose search fails is skipped rather than counted as zero, and
    the caller is told through `partial` so a transient failure never silently
    reads as "nobody has this tag".
    """
    people, partial = {}, []
    for label, client in clients:
        try:
            found = client.search_contacts(
                filters=[{'field': 'tags', 'operator': 'eq', 'value': tag}])
            for contact in found:
                record = people.setdefault(identity(contact),
                                           {'tags': set(), 'ids': set(),
                                            'accounts': set(), 'dnd': False})
                record['tags'].update(t.lower() for t in (contact.get('tags') or []))
                record['ids'].add(contact['id'])
                record['accounts'].add(label)
                record['dnd'] = record['dnd'] or bool(contact.get('dnd'))
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            partial.append('%s: %s' % (label, exc))
    return people, partial
