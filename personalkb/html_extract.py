from html.parser import HTMLParser
from html import escape
import re


class _Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.svg = []
        self.svg_parts = None
        self.svg_depth = 0
        self.skip = []
        self.title_parts = []
        self.in_title = False
        self.pre = False
        self.rows = None
        self.row = None
        self.cell = None
        self.table_stack = []
        self.links = []
        self.warnings = set()
        self.stats = {'table': 0, 'code': 0, 'svg': 0, 'formula': 0}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.skip:
            if tag in ('script', 'style', 'foreignobject'): self.skip.append(tag)
            return
        if tag in ('script', 'style', 'foreignobject'):
            self.skip.append(tag)
            if tag != 'style': self.warnings.add('脚本或嵌入内容已忽略')
            return
        if self.svg_depth:
            self.svg_depth += 1
            self.svg_parts.append(self._tag(tag, attrs))
            return
        if tag == 'svg':
            self.svg_depth = 1
            self.svg_parts = [self._tag(tag, attrs)]
            self.stats['svg'] += 1
        elif tag == 'title': self.in_title = True
        elif tag == 'canvas': self.warnings.add('动态画布无法提取，请补充静态导出')
        elif tag == 'img': self.warnings.add('图片未获取或识别，请补充静态导出')
        elif tag == 'math':
            self.stats['formula'] += 1
            self.warnings.add('公式仅提取文本，结构可能丢失，请核对静态导出')
            self.out.append('\n[公式: ')
        elif tag in ('iframe', 'object', 'embed'):
            self.warnings.add('嵌入内容未获取，请补充静态导出')
        elif re.fullmatch(r'h[1-6]', tag): self.out.append('\n\n' + '#' * int(tag[1]) + ' ')
        elif tag in ('p', 'div', 'section', 'article', 'br'): self.out.append('\n')
        elif tag == 'li': self.out.append('\n- ')
        elif tag == 'pre':
            self.pre = True
            self.stats['code'] += 1
            self.out.append('\n```\n')
        elif tag == 'table':
            if self.rows is not None:
                self.table_stack.append((self.rows, self.row, self.cell))
                self.warnings.add('嵌套表格已展平，请核对原文')
            self.rows = []
            self.row = None
            self.cell = None
            self.stats['table'] += 1
        elif tag == 'tr' and self.rows is not None: self.row = []
        elif tag in ('td', 'th') and self.row is not None: self.cell = []
        elif tag == 'a': self.links.append(attrs.get('href', ''))

    def _tag(self, tag, attrs):
        # SVG is evidence text only; remove active attributes and external references.
        clean = []
        for key, value in attrs.items():
            if key.startswith('on') or key in ('href', 'xlink:href', 'style'):
                self.warnings.add('SVG 活动属性或外部引用已忽略')
                continue
            clean.append(' ' + key + '="' + escape(value or '', quote=True) + '"')
        return '<' + tag + ''.join(clean) + '>'

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip[-1]: self.skip.pop()
            return
        if self.svg_depth:
            self.svg_parts.append('</' + tag + '>')
            self.svg_depth -= 1
            if not self.svg_depth:
                self.svg.append(''.join(self.svg_parts))
                self.out.append('\n[SVG 结构见证据 %d]\n' % len(self.svg))
            return
        if tag == 'title': self.in_title = False
        elif tag == 'math': self.out.append(']\n')
        elif tag == 'pre':
            self.pre = False
            self.out.append('\n```\n')
        elif tag in ('td', 'th') and self.cell is not None:
            self.row.append(''.join(self.cell).strip().replace('|', r'\|'))
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        elif tag == 'table' and self.rows is not None:
            if self.table_stack:
                nested = ' '.join(' '.join(row) for row in self.rows)
                self.rows, self.row, self.cell = self.table_stack.pop()
                if self.cell is not None: self.cell.append(' ' + nested + ' ')
                else: self.out.append(nested)
            elif self.rows:
                rows = [self.rows[0], ['---'] * len(self.rows[0]), *self.rows[1:]]
                self.out.append('\n' + '\n'.join('| ' + ' | '.join(row) + ' |' for row in rows) + '\n')
                self.rows = None
            else: self.rows = None
        elif tag == 'a' and self.links:
            href = self.links.pop()
            if href: self.out.append(' (' + href + ')')
        elif tag in ('p', 'li') or re.fullmatch(r'h[1-6]', tag): self.out.append('\n')

    def handle_data(self, data):
        if self.skip: return
        if self.svg_depth:
            self.svg_parts.append(escape(data))
        elif self.in_title: self.title_parts.append(data)
        elif self.cell is not None: self.cell.append(data)
        elif self.row is None: self.out.append(data if self.pre else re.sub(r'\s+', ' ', data))


def extract_html(content):
    """Extract static evidence from HTML text without loading external resources."""
    if not isinstance(content, str): raise TypeError('content must be text')
    parser = _Extractor()
    parser.feed(content)
    parser.close()
    if parser.svg_depth:
        parser.warnings.add('SVG 结构不完整，请补充静态导出')
        parser.svg.append(''.join(parser.svg_parts))
    return {'title': ''.join(parser.title_parts).strip(), 'body': ''.join(parser.out).strip(),
            'svg_context': '\n'.join(parser.svg), 'warnings': sorted(parser.warnings), 'stats': parser.stats}
