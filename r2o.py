import sys
import os
import json
from tqdm import tqdm
import re
from dateutil.parser import parse
from datetime import datetime

yaml = '''---
title:   {title}
created: {created}
---

'''

re_daily = re.compile(r'(January|February|March|April|May|June|July|August|September|October|November|December) ([0-9]+)[a-z]{2}, ([0-9]{4})')
re_daylink = re.compile(r'(\[\[)([January|February|March|April|May|June|July|August|September|October|November|December [0-9]+[a-z]{2}, [0-9]{4})(\]\])')
re_blockmentions = re.compile(r'({{mentions: \(\()(.{9})(\)\)}})')
re_blockembed = re.compile(r'({{embed: \(\()(.{9})(\)\)}})')
re_blockref = re.compile(r'(\(\()(.{9})(\)\))')

def scan(jdict, page):
    u2b = {jdict['uid']: jdict}
    for child in jdict.get('children', []):
        child['page'] = page
        u2b.update(scan(child, page))
    return u2b


def replace_daylinks(s):
    new_s = s
    while True:
        m = re_daylink.search(new_s)
        if not m:
            break
        else:
            head = new_s[:m.end(1)]
            dt = parse(m.group(2))
            replacement = dt.isoformat()[:10]
            tail = ']]' + new_s[m.end(0):] 
            new_s = head + replacement + tail
    return new_s


def replace_blockrefs(s, uid2block, referenced_uids):
    new_s = s
    while True:
        m = re_blockembed.search(new_s)
        if m is None:
            m = re_blockmentions.search(new_s)
            if m is None:
                m = re_blockref.search(new_s)
        if m is None:
            break
        else:
            uid = m.group(2)
            if uid not in uid2block:
                print('************** uid not found:', uid)
            else:
                referenced_uids.add(uid)
                head = new_s[:m.start(1)]
                r_block = uid2block[uid]
                # shall we replace with the text or the link or both
                replacement = r_block['string']
                replacement += f' [[{r_block["page"]["title"]}#^{r_block["uid"]}]]'
                tail = new_s[m.end(3):]
                new_s = head + replacement + tail
    return replace_daylinks(new_s)


def expand_children(block, uid2block, referenced_uids, level=0):
    lines = []
    for b in block.get('children', []):
        prefix = ''
        if level >= 1:
            prefix = '    ' * level
        s = b['string']
        children = b.get('children', None)

        if children is None and level == 0:
            pass
        else:
            prefix += '- ' 

        headinglevel = b.get('heading', None)
        if headinglevel is not None:
            prefix = prefix + '#' * (headinglevel) + ' ' 


        uid = b['uid']
        if uid in referenced_uids:
            postfix = f' ^{uid}'
        else:
            postfix = ''

        todo_match = re.match('{+\[\[(DONE|TODO)\]\]}+', s)
        if todo_match:
            match_str = todo_match.group(0)
            todo_text = '[ ]' if 'TODO' in match_str else '[x]'
            s = s.replace(match_str, todo_text, 1)

        # b id magic
        s = prefix + replace_blockrefs(s, uid2block, referenced_uids) + postfix
        if '\n' in s:
            new_s = s[:-1]
            new_s = new_s.replace('\n', '\n'+prefix)
            new_s += s[-1]
            s = new_s + '\n'

        lines.append(s)
        lines.extend(expand_children(b, uid2block, referenced_uids, level + 1))
    return lines


j = json.load(open(sys.argv[1], mode='rt', encoding='utf-8', errors='ignore'))

odir = 'md'
ddir = 'md/daily'
wdir = 'md/weekly_plans'
os.makedirs(ddir, exist_ok=True)
os.makedirs(wdir, exist_ok=True)

print('Pass 1: scan all pages')

uid2block = {}
referenced_uids = set()
pages = []

for page in tqdm(j):
    title = page['title']
    created = page.get('create-time', page['edit-time'])
    created = datetime.fromtimestamp(created/1000).isoformat()[:10]
    children = page.get('children', [])

    is_daily = False
    is_weekly = False
    m = re_daily.match(title)
    w = title[:13] == 'Weekly Plan: '
    if m:
        is_daily = True
        dt = parse(title)
        title = dt.isoformat().split('T')[0]
    elif w:
        is_weekly = True
        dt = parse(title[13:])
        title = title[:13] + dt.isoformat().split('T')[0]

    page = {
        'uid': None,
        'title': title,
        'created': created,
        'children': children,
        'daily': is_daily,
        'weekly': is_weekly
        }
    uid2block.update(scan(page, page))
    pages.append(page)

print('Pass 2: track blockrefs')
for p in tqdm(pages):
    expand_children(p, uid2block, referenced_uids)

print('Pass 3: generate')
error_pages = []
for p in tqdm(pages):
    title = p['title']
    if not title:
        continue
    ofiln = f'{odir}/{p["title"]}.md'
    if p['daily']:
        ofiln = f'{ddir}/{p["title"]}.md'
    elif p['weekly']:
        ofiln = f'{wdir}/{p["title"]}.md'

    # hack for crazy slashes in titles 
    if '/' in title:
        d = odir
        for part in title.split('/')[:-1]:
            d = os.path.join(d, part)
            os.makedirs(d, exist_ok=True)

    lines = expand_children(p, uid2block, referenced_uids)
    try:
        with open(ofiln, mode='wt', encoding='utf-8') as f:
            f.write(yaml.format(**p))
            f.write('\n'.join(lines))
    except:
        error_pages.append({'page':p, 'content': lines})

if error_pages:
    print('The following pages had errors:')
    for ep in error_pages:
        p = ep['page']
        t = p['title']
        c = ep['content']
        print(f'Title: >{t}<')
        print(f'Content:')
        print('    ' + '\n    '.join(c))
print('Done!')
