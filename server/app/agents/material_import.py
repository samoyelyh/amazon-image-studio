"""Path hints are data; never paths to extract on the server or tool instructions."""
import re
import unicodedata
from pathlib import PurePosixPath

NAMES={
    'template':{'template','templates','model','models','模板','模板图','模特','模特模板'},
    'garment':{'garment','garments','clothes','clothing','服装','衣服','球衣','待套服装','服装原图','服装主图'},
    'front':{'front','正面','正面图'},'back':{'back','背面','背面图'},
    'detail':{'detail','details','细节','细节图'},'font':{'font','fonts','字体','字体图','图c'},
}


def safe_path(value):
    value=unicodedata.normalize('NFC',value.replace('\\','/'))
    parts=value.split('/')
    if not value or value.startswith('/') or len(value)>1000 or len(parts)>16 or any(
        p in ('','.','..') or len(p)>255 or ':' in p or any(ord(c)<32 or ord(c)==127 or '\u202a'<=c<='\u202e' or '\u2066'<=c<='\u2069' for c in p) for p in parts):
        raise ValueError('素材路径无效：仅允许安全的相对路径')
    return value


def assignment(info):
    """Explicit source wins; view/SKU/folder hints bind logical products, not people."""
    path=PurePosixPath(safe_path(info.relative_path));parts=[p.casefold() for p in path.parts]
    stem=path.stem.casefold()
    role='reference';origin='unresolved'
    if info.source=='template':role,origin='template','explicit'
    elif info.source=='garment':role,origin='garment','explicit'
    else:
        for part in parts[:-1]:
            if part in NAMES['template']:role,origin='template','directory'
            elif part in NAMES['garment']:role,origin='garment','directory'
    if role!='template':
        for kind in ('front','back','detail','font'):
            if any(p in NAMES[kind] for p in parts[:-1]) or re.search(
                r'(?:^|[-_\s])(?:'+ '|'.join(re.escape(p) for p in NAMES[kind])+r')(?:[-_\s]*\d+)?$',stem):
                role,origin=kind,origin if origin=='explicit' else 'directory'
                break
    if role=='template':return role,'',origin
    sku=re.search(r'(?:nf[-_ ]?)?(\d{7,})',str(path).casefold())
    if sku:return role,'sku:'+sku[1],origin
    view_only=any(re.fullmatch('(?:'+'|'.join(re.escape(p) for p in names)+r')(?:[-_\s]*\d+)?',stem) for k,names in NAMES.items() if k in ('front','back','detail','font'))
    if view_only:
        candidates=[p for p in path.parts[:-1] if p.casefold() not in set().union(*NAMES.values())]
        if candidates:return role,'folder:'+'/'.join(candidates).casefold(),origin
    if role=='reference':return role,'',origin
    from app.agents.batch_manifest import filename_group
    return role,filename_group(path.name),origin
