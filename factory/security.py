"""Shared policy for static tools; no third-party code or network forms."""
import html
import re
from html.parser import HTMLParser


CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; "
       "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
       "manifest-src 'self'; object-src 'none'; base-uri 'none'; "
       "form-action 'none'; frame-src 'none'; worker-src 'none'")


def security_headers(*, https=False):
    headers = {
        'Content-Security-Policy': CSP + "; frame-ancestors 'none'",
        'X-Content-Type-Options': 'nosniff',
        'Referrer-Policy': 'no-referrer',
        'X-Frame-Options': 'DENY',
        'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=(), usb=()',
    }
    if https:
        headers['Strict-Transport-Security'] = 'max-age=31536000'
    return headers


def headers_file():
    return '/*\n' + ''.join(f'  {name}: {value}\n' for name, value in security_headers(https=True).items())


def protect_html(page):
    """Insert before resources, preserving source bytes and existing stricter policies.

    Meta enforces CSP even on hosts that ignore _headers. Frame protection and
    the other HTTP-only headers still require support from the serving host.
    """
    offsets = [0] + [i + 1 for i, char in enumerate(page) if char == '\n']

    class Head(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.head = None
            self.opening = 0
            self.tags = []
            self.inert = 0

        def position(self):
            line, column = self.getpos()
            return offsets[line - 1] + column

        def handle_decl(self, decl):
            if decl.lower().startswith('doctype ') and not self.tags:
                self.opening = page.find('>', self.position()) + 1

        def handle_starttag(self, tag, attrs):
            if not self.inert:
                start = self.position()
                end = start + len(self.get_starttag_text())
                self.tags.append((tag, start))
                if tag == 'html' and not any(t != 'html' for t, _ in self.tags):
                    self.opening = end
                if tag == 'head' and self.head is None:
                    self.head = end
            if tag == 'template':
                self.inert += 1

        def handle_endtag(self, tag):
            if tag == 'template':
                self.inert = max(0, self.inert - 1)

        def handle_startendtag(self, tag, attrs):
            self.handle_starttag(tag, attrs)
            self.handle_endtag(tag)

    parsed = Head()
    parsed.feed(page)
    parsed.close()
    point = parsed.head if parsed.head is not None else parsed.opening
    if any(tag not in {'html', 'head'} and start < point for tag, start in parsed.tags):
        raise ValueError('El HTML debe situar head antes del contenido para aplicar la CSP')
    meta = ('<meta http-equiv="Content-Security-Policy" content="' + html.escape(CSP, quote=True)
            + '"><meta name="referrer" content="no-referrer">')
    if parsed.head is None:
        meta = '<head>' + meta + '</head>'
    else:
        # Browsers only sniff the first 1024 bytes for the encoding: keep the charset declaration first.
        close = page.lower().find('</head>', point)
        charset = re.compile(r"""<meta\s+charset\s*=\s*["']?utf-8["']?\s*/?>""", re.I).search(page, point, len(page) if close < 0 else close)
        if charset:
            meta = charset.group(0) + meta
            page = page[:charset.start()] + page[charset.end():]
    return page[:point] + meta + page[point:]
