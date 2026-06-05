"""
mslang 词法解析器 (Lexer)

将源文本扫描为 Token 流。采用两阶段策略：
  1. 块级扫描：按行识别标题、代码块、列表、引用、分割线、段落边界
  2. 行内扫描：在段落/标题等块内容中识别加粗、斜体、链接等行内元素

支持精确的位置追踪（行号、列号、字符索引）。
"""

import re
from typing import List, Optional
from .tokens import (
    Token, TokenType, Position,
    BACKTICK, STAR, UNDERSCORE, TILDE, AT, SLASH,
    BANG, LBRACKET, RBRACKET, LPAREN, RPAREN, PIPE,
    NEWLINE,
)


# ================================================================
# 工具函数（模块级，供 Lexer 和 Parser 共享使用）
# ================================================================

def parse_function_args(raw: str):
    """
    解析函数参数: 位置参数 + 关键字参数。
    供 Lexer 和 Parser 共同使用。

    支持:
      - 裸词: hello → "hello"
      - 引号字符串: "hello world" → "hello world"
      - 数字: 42 → "42"
      - key=value: name="John"
      - 混合: name, age=30, color="red"

    Returns:
        (args: List[str], kwargs: Dict[str, str])
    """
    args = []
    kwargs = {}
    raw = raw.strip()
    if not raw:
        return args, kwargs

    current = ''
    in_single = False
    in_double = False
    parts = []

    for ch in raw:
        if ch == "'" and not in_double:
            in_single = not in_single
            current += ch
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            current += ch
            continue
        if ch == ',' and not in_single and not in_double:
            parts.append(current.strip())
            current = ''
            continue
        current += ch
    if current.strip():
        parts.append(current.strip())

    for part in parts:
        eq_pos = -1
        for j, ch in enumerate(part):
            if ch == '=':
                in_q = False
                q_ch = None
                for k in range(j):
                    if part[k] in ('"', "'"):
                        if in_q and part[k] == q_ch:
                            in_q = False
                        elif not in_q:
                            in_q = True
                            q_ch = part[k]
                if not in_q:
                    eq_pos = j
                    break
        if eq_pos > 0:
            key = part[:eq_pos].strip()
            val = part[eq_pos + 1:].strip()
            val = unquote(val)
            kwargs[key] = val
        else:
            args.append(unquote(part))

    return args, kwargs


def unquote(s: str) -> str:
    """去掉字符串两端的引号"""
    s = s.strip()
    if len(s) >= 2:
        if (s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'"):
            return s[1:-1]
    return s


class LexerError(Exception):
    """词法分析错误"""
    def __init__(self, message: str, position: Position):
        super().__init__(f"[{position}] {message}")
        self.position = position


class Lexer:
    """
    mslang 词法解析器

    使用方式:
        lexer = Lexer(source_text)
        tokens = lexer.tokenize()
        for token in tokens:
            print(token)
    """

    # 正则模式
    RE_HEADING        = re.compile(r'^(#{1,6})\s+(.+)$')
    RE_HORIZONTAL_RULE = re.compile(r'^(\s{0,3})([-*_])\s*\2\s*\2[ \2]*$')  # ---, ***, ___
    RE_BLOCKQUOTE     = re.compile(r'^>\s?(.*)$')
    RE_UNORDERED_LIST = re.compile(r'^(\s*)([-*+])\s+(.+)$')
    RE_ORDERED_LIST   = re.compile(r'^(\s*)(\d+)\.\s+(.+)$')
    RE_FOOTNOTE_DEF   = re.compile(r'^\[\^([^\]]+)\]:\s+(.+)$')
    RE_TABLE          = re.compile(r'^\|(.+)\|$')
    RE_ALIGN_RIGHT    = re.compile(r'^>>\s+(.+)$')
    RE_ALIGN_CENTER   = re.compile(r'^-><-\s+(.+)$')

    def __init__(self, source: str):
        """
        Args:
            source: 原始 mslang 格式文本
        """
        self.source = source
        self.pos = 0           # 当前字符索引
        self.line = 1          # 当前行号
        self.col = 1           # 当前列号
        self._in_code_block = False  # 是否在代码块内部

    # ================================================================
    # 公共接口
    # ================================================================

    def tokenize(self) -> List[Token]:
        """
        扫描全部源文本，返回 Token 列表。

        Returns:
            List[Token]: 包含 EOF 的完整 Token 序列
        """
        tokens: List[Token] = []
        self.pos = 0
        self.line = 1
        self.col = 1
        self._in_code_block = False

        while self.pos < len(self.source):
            token = self._next_token()
            if token is not None:
                tokens.append(token)

        # EOF
        tokens.append(Token(
            type=TokenType.EOF,
            position=Position(self.line, self.col, self.pos),
        ))
        return tokens

    # ================================================================
    # 主分发
    # ================================================================

    def _next_token(self) -> Optional[Token]:
        """读取下一个 Token"""
        ch = self._peek()
        if ch is None:
            return None

        # 换行符
        if ch == NEWLINE:
            return self._scan_newline()

        # 行首判断 — 块级元素
        if self.col == 1:
            return self._scan_block_start()

        # 行内判断
        return self._scan_inline()

    # ================================================================
    # 行首块级扫描
    # ================================================================

    def _scan_block_start(self) -> Token:
        """在行首位置判断当前行属于哪种块级类型"""
        remaining = self.source[self.pos:self._line_end()]

        # 代码块开始/结束
        if remaining.startswith('```'):
            return self._scan_code_block_fence()

        # 如果在代码块内部
        if self._in_code_block:
            return self._scan_code_block_line()

        # 水平分割线
        m = self.RE_HORIZONTAL_RULE.match(remaining)
        if m:
            return self._scan_horizontal_rule(m)

        # 脚注定义 [^label]: content
        m = self.RE_FOOTNOTE_DEF.match(remaining)
        if m:
            return self._scan_footnote_def(m)

        # 对齐（必须在 blockquote 之前检查，以免 >> 被当成 >）
        m = self.RE_ALIGN_RIGHT.match(remaining)
        if m:
            return self._scan_align(m, TokenType.ALIGN_RIGHT)

        m = self.RE_ALIGN_CENTER.match(remaining)
        if m:
            return self._scan_align(m, TokenType.ALIGN_CENTER)

        # 标题
        m = self.RE_HEADING.match(remaining)
        if m:
            return self._scan_heading(m)

        # 引用
        m = self.RE_BLOCKQUOTE.match(remaining)
        if m:
            return self._scan_blockquote(m)

        # 无序列表
        m = self.RE_UNORDERED_LIST.match(remaining)
        if m:
            return self._scan_unordered_list(m)

        # 有序列表
        m = self.RE_ORDERED_LIST.match(remaining)
        if m:
            return self._scan_ordered_list(m)

        # 表格
        m = self.RE_TABLE.match(remaining)
        if m:
            return self._scan_table_row(m)

        # 默认为行内文本（包括嵌套格式如 **bold**, *italic*, 图片等）
        return self._scan_inline()

    # ================================================================
    # 行内扫描
    # ================================================================

    def _scan_inline(self) -> Token:
        """在非行首位置扫描行内元素"""
        ch = self._peek()

        # 加粗或斜体**
        if ch == STAR:
            return self._scan_star_delimited()

        # 加粗或斜体__
        if ch == UNDERSCORE:
            return self._scan_underscore_delimited()

        # 删除线 ~~ 或下标 ~text~
        if ch == TILDE:
            return self._scan_tilde_delimited()

        # 上标 ^text^
        if ch == '^':
            return self._scan_superscript()

        # 行内代码 `
        if ch == BACKTICK:
            return self._scan_inline_code()

        # 链接或图片 [ 或 ![
        if ch == BANG:
            next_ch = self._peek_at(self.pos + 1)
            if next_ch == LBRACKET:
                return self._scan_image()
            return self._scan_raw_text()

        if ch == LBRACKET:
            # 脚注引用 [^label]
            if self._peek_at(self.pos + 1) == '^':
                return self._scan_footnote_ref()
            return self._scan_link()

        # 自定义函数调用 @fn(args)
        if ch == AT:
            return self._scan_function_call()

        # 颜色文本 /#hex:text:/
        if ch == SLASH:
            next_ch = self._peek_at(self.pos + 1)
            if next_ch == '#':
                return self._scan_color()

        # 默认：原始文本
        return self._scan_raw_text()

    # ================================================================
    # 具体扫描方法 — 块级
    # ================================================================

    def _scan_heading(self, match: re.Match) -> Token:
        """扫描标题 Token，支持 {#id}"""
        hashes = match.group(1)
        content = match.group(2)
        level = len(hashes)
        # 提取 {#id}
        import re as _re
        id_m = _re.search(r'\s*\{#([^}]+)\}\s*$', content)
        heading_id = ''
        if id_m:
            heading_id = id_m.group(1)
            content = content[:id_m.start()].rstrip()
        start = self.pos
        self._advance(len(hashes) + 1 + len(match.group(2)))
        return Token(
            type=TokenType.HEADING,
            position=Position(self.line, self.col - len(hashes) - 1 - len(match.group(2)), start),
            value=content,
            metadata={'level': level, 'id': heading_id}
        )

    def _scan_horizontal_rule(self, match: re.Match) -> Token:
        """扫描分割线 Token"""
        length = match.end() - match.start()
        start = self.pos
        self._advance(length)
        return Token(
            type=TokenType.HORIZONTAL_RULE,
            position=Position(self.line, self.col - length, start),
            value=match.group(0).strip(),
        )

    def _scan_blockquote(self, match: re.Match) -> Token:
        """扫描引用块 Token"""
        content = match.group(1)
        length = match.end() - match.start()
        start = self.pos
        self._advance(length)
        return Token(
            type=TokenType.BLOCKQUOTE,
            position=Position(self.line, self.col - length, start),
            value=content,
        )

    def _scan_unordered_list(self, match: re.Match) -> Token:
        """扫描无序列表 Token"""
        indent = match.group(1)
        marker = match.group(2)
        content = match.group(3)
        length = match.end() - match.start()
        start = self.pos
        self._advance(length)
        return Token(
            type=TokenType.UNORDERED_LIST,
            position=Position(self.line, self.col - length, start),
            value=content,
            metadata={'indent': len(indent), 'marker': marker}
        )

    def _scan_ordered_list(self, match: re.Match) -> Token:
        """扫描有序列表 Token"""
        indent = match.group(1)
        number = match.group(2)
        content = match.group(3)
        length = match.end() - match.start()
        start = self.pos
        self._advance(length)
        return Token(
            type=TokenType.ORDERED_LIST,
            position=Position(self.line, self.col - length, start),
            value=content,
            metadata={'indent': len(indent), 'number': int(number)}
        )

    def _scan_table_row(self, match: re.Match) -> Token:
        """扫描表格行 | cell | cell |"""
        inner = match.group(1).strip()
        length = match.end() - match.start()
        start = self.pos
        self._advance(length)

        # 检查是否为分隔行 |---|---|
        cells = [c.strip() for c in inner.split('|')]
        is_sep = all(c and all(ch in '-: ' for ch in c) for c in cells)
        return Token(
            type=TokenType.TABLE_SEP if is_sep else TokenType.TABLE_ROW,
            position=Position(self.line, self.col - length, start),
            value=inner,
            metadata={'cells': cells},
        )

    def _scan_code_block_fence(self) -> Token:
        """扫描代码块围栏 ``` """
        start_pos = Position(self.line, self.col, self.pos)
        line_end = self._line_end()

        # 提取围栏行
        fence_line = self.source[self.pos:line_end]
        self._advance(len(fence_line))

        if self._in_code_block:
            self._in_code_block = False
            return Token(
                type=TokenType.CODE_BLOCK,
                position=start_pos,
                value='',
                metadata={'fence_type': 'end'}
            )
        else:
            self._in_code_block = True
            language = fence_line[3:].strip()  # 去掉 ``` 后的语言标识
            return Token(
                type=TokenType.CODE_BLOCK,
                position=start_pos,
                value='',
                metadata={'fence_type': 'start', 'language': language}
            )

    def _scan_code_block_line(self) -> Token:
        """扫描代码块内部行"""
        start = self.pos
        line_end = self._line_end()
        content = self.source[start:line_end]
        pos = Position(self.line, self.col, start)
        self._advance(len(content))
        return Token(
            type=TokenType.RAW_TEXT,
            position=pos,
            value=content,
            metadata={'in_code_block': True}
        )

    # ================================================================
    # 具体扫描方法 — 行内
    # ================================================================

    def _scan_star_delimited(self) -> Token:
        """扫描 ** / * 限定的行内格式"""
        # 检查是否是 **bold**
        next_ch = self._peek_at(self.pos + 1)
        if next_ch == STAR:
            return self._scan_delimiter_wrapped(TokenType.BOLD, STAR * 2)
        return self._scan_delimiter_wrapped(TokenType.ITALIC, STAR)

    def _scan_underscore_delimited(self) -> Token:
        """扫描 __ / _ 限定的行内格式"""
        next_ch = self._peek_at(self.pos + 1)
        if next_ch == UNDERSCORE:
            return self._scan_delimiter_wrapped(TokenType.BOLD, UNDERSCORE * 2)
        return self._scan_delimiter_wrapped(TokenType.ITALIC, UNDERSCORE)

    def _scan_tilde_delimited(self) -> Token:
        """扫描 ~~ 删除线 或 ~下标~"""
        next_ch = self._peek_at(self.pos + 1)
        if next_ch == TILDE:
            return self._scan_delimiter_wrapped(TokenType.STRIKETHROUGH, TILDE * 2)
        # 单个 ~ : 扫描下标
        return self._scan_single_delimited(TokenType.SUBSCRIPT, '~')

    def _scan_superscript(self) -> Token:
        """扫描 ^上标^"""
        return self._scan_single_delimited(TokenType.SUPERSCRIPT, '^')

    def _scan_single_delimited(self, token_type: TokenType, delim: str) -> Token:
        """扫描由单个字符对称包裹的 Token（上标/下标）"""
        start_pos = Position(self.line, self.col, self.pos)
        self._advance(1)
        end_idx = self.source.find(delim, self.pos)
        if end_idx == -1 or end_idx == self.pos:
            return self._fallback_raw_text(start_pos, delim)
        inner = self.source[self.pos:end_idx]
        self._advance(len(inner) + 1)
        return Token(
            type=token_type,
            position=start_pos,
            value=inner,
        )

    def _scan_delimiter_wrapped(self, token_type: TokenType, delimiter: str) -> Token:
        """
        扫描由对称分隔符包裹的 Token（加粗/斜体/删除线）

        策略：找到下一个匹配的结束分隔符，提取中间内容作为 value。
        """
        start_pos = Position(self.line, self.col, self.pos)
        del_len = len(delimiter)
        self._advance(del_len)  # 跳过开始分隔符

        # 查找结束分隔符
        end_idx = self.source.find(delimiter, self.pos)
        if end_idx == -1:
            # 未找到结束分隔符，回退并当作普通文本
            inner = self.source[start_pos.index + del_len:self.pos]
            # 不完整格式 — 将起始分隔符也作为文本
            # 实际上这时我们已经 consume 了起始分隔符，简单处理
            return Token(
                type=TokenType.RAW_TEXT,
                position=start_pos,
                value=delimiter
            )

        # 提取内容
        content = self.source[self.pos:end_idx]

        # 前进到结束分隔符之后
        self._advance(len(content) + del_len)

        return Token(
            type=token_type,
            position=start_pos,
            value=content,
        )

    def _scan_inline_code(self) -> Token:
        """扫描行内代码 `code`"""
        start_pos = Position(self.line, self.col, self.pos)
        self._advance(1)  # 跳过开始 `

        end_idx = self.source.find(BACKTICK, self.pos)
        if end_idx == -1:
            return Token(type=TokenType.RAW_TEXT, position=start_pos, value=BACKTICK)

        code = self.source[self.pos:end_idx]
        self._advance(len(code) + 1)  # 跳过内容和结束 `

        return Token(
            type=TokenType.INLINE_CODE,
            position=start_pos,
            value=code,
        )

    def _scan_footnote_ref(self) -> Token:
        """扫描脚注引用 [^label]"""
        start_pos = Position(self.line, self.col, self.pos)
        self._advance(2)  # 跳过 [^
        end = self.source.find(']', self.pos)
        if end == -1 or end == self.pos:
            return self._fallback_raw_text(start_pos, '[^')
        label = self.source[self.pos:end]
        self._advance(len(label) + 1)
        return Token(
            type=TokenType.FOOTNOTE_REF,
            position=start_pos,
            value=label,
        )

    def _scan_footnote_def(self, match: re.Match) -> Token:
        """扫描脚注定义 [^label]: content"""
        label = match.group(1)
        content = match.group(2)
        length = match.end() - match.start()
        start = self.pos
        self._advance(length)
        return Token(
            type=TokenType.FOOTNOTE_DEF,
            position=Position(self.line, self.col - length, start),
            value=content,
            metadata={'label': label},
        )

    def _scan_align(self, match: re.Match, token_type: TokenType) -> Token:
        """扫描对齐块 >> text 或 -><- text"""
        content = match.group(1)
        length = match.end() - match.start()
        start = self.pos
        self._advance(length)
        return Token(
            type=token_type,
            position=Position(self.line, self.col - length, start),
            value=content,
        )

    def _scan_link(self) -> Token:
        """扫描链接 [text](url)"""
        start_pos = Position(self.line, self.col, self.pos)
        self._advance(1)  # 跳过 [

        # 提取链接文本
        text_end = self.source.find(RBRACKET, self.pos)
        if text_end == -1:
            return self._fallback_raw_text(start_pos, '[')

        text = self.source[self.pos:text_end]
        self._advance(len(text) + 1)  # 跳过 text + ]

        # 检查是否跟着 (
        if self._peek() == LPAREN:
            self._advance(1)  # 跳过 (
            url_end = self.source.find(RPAREN, self.pos)
            if url_end == -1:
                # 没有闭合括号，回退
                return self._fallback_raw_text(start_pos, f'[{text}]')
            url = self.source[self.pos:url_end]
            self._advance(len(url) + 1)  # 跳过 url + )
            return Token(
                type=TokenType.LINK,
                position=start_pos,
                value=text,
                metadata={'url': url}
            )

        # 不是链接，回退为普通文本
        return self._fallback_raw_text(start_pos, f'[{text}]')

    def _scan_image(self) -> Token:
        """扫描图片 ![alt](url)"""
        start_pos = Position(self.line, self.col, self.pos)
        self._advance(2)  # 跳过 ![

        alt_end = self.source.find(RBRACKET, self.pos)
        if alt_end == -1:
            return self._fallback_raw_text(start_pos, '![')

        alt = self.source[self.pos:alt_end]
        self._advance(len(alt) + 1)  # 跳过 alt + ]

        if self._peek() == LPAREN:
            self._advance(1)
            url_end = self.source.find(RPAREN, self.pos)
            if url_end == -1:
                return self._fallback_raw_text(start_pos, f'![{alt}]')
            url_raw = self.source[self.pos:url_end]
            # 解析 URL 和可选宽度百分比
            url = url_raw.strip()
            width = ''
            if ' ' in url:
                parts = url.rsplit(' ', 1)
                if parts[1].endswith('%') and parts[1][:-1].isdigit():
                    url = parts[0]
                    width = parts[1]
            self._advance(len(url_raw) + 1)
            return Token(
                type=TokenType.IMAGE,
                position=start_pos,
                value=alt,
                metadata={'url': url, 'width': width}
            )

        return self._fallback_raw_text(start_pos, f'![{alt}]')

    def _scan_function_call(self) -> Token:
        """扫描自定义函数调用 @name(args)"""
        start_pos = Position(self.line, self.col, self.pos)
        self._advance(1)  # 跳过 @

        # 扫描函数名 [a-zA-Z_][a-zA-Z0-9_]*
        name_start = self.pos
        while self.pos < len(self.source) and (
            self.source[self.pos].isalnum() or self.source[self.pos] == '_'
        ):
            self._advance(1)

        if self.pos == name_start:
            # @ 后面没有合法标识符，回退为原始文本
            return self._fallback_raw_text(start_pos, '@')

        func_name = self.source[name_start:self.pos]

        # 必须有 (
        if self._peek() != LPAREN:
            return self._fallback_raw_text(start_pos, f'@{func_name}')

        self._advance(1)  # 跳过 (

        # 扫描参数直到 )
        rparen = self.source.find(RPAREN, self.pos)
        if rparen == -1:
            # 没有闭合括号，回退
            return self._fallback_raw_text(start_pos, f'@{func_name}(')

        raw_args = self.source[self.pos:rparen]
        self._advance(len(raw_args) + 1)  # 跳过参数和 )

        # 解析参数
        args, kwargs = self._parse_function_args(raw_args)

        return Token(
            type=TokenType.FUNCTION_CALL,
            position=start_pos,
            value=func_name,
            metadata={
                'args': args,
                'kwargs': kwargs,
                'raw_args': raw_args,
            }
        )

    @staticmethod
    def _parse_function_args(raw: str):
        """委托到模块级函数"""
        return parse_function_args(raw)

    @staticmethod
    def _unquote(s: str) -> str:
        """委托到模块级函数"""
        return unquote(s)

    def _scan_color(self) -> Token:
        """扫描颜色文本 /#hex:text:/"""
        start_pos = Position(self.line, self.col, self.pos)
        self._advance(2)  # 跳过 /#

        # 扫描 hex 颜色 (3或6位)
        color_start = self.pos
        while self.pos < len(self.source) and self.source[self.pos] in '0123456789abcdefABCDEF':
            self._advance(1)
        color = self.source[color_start:self.pos]
        if len(color) not in (3, 6):
            return self._fallback_raw_text(start_pos, f'/#{color}')

        # 必须有 :
        if self._peek() != ':':
            return self._fallback_raw_text(start_pos, f'/#{color}')
        self._advance(1)

        # 扫描文本直到 :/
        end_marker = self.source.find(':/', self.pos)
        if end_marker == -1:
            return self._fallback_raw_text(start_pos, f'/#{color}:')
        text = self.source[self.pos:end_marker]
        self._advance(len(text) + 2)  # 跳过文本和 :/

        return Token(
            type=TokenType.COLOR,
            position=start_pos,
            value=text,
            metadata={'color': color}
        )

    def _scan_newline(self) -> Token:
        """扫描换行符。如果连续两个换行（空行），返回 BLANK_LINE"""
        start_pos = Position(self.line, self.col, self.pos)
        self._advance(1)  # 跳过 \n

        # 检测空行：当前在行首 + 下一个字符也是换行
        if self.col == 1 and self._peek() == NEWLINE:
            self._advance(1)
            return Token(
                type=TokenType.BLANK_LINE,
                position=start_pos,
                value='\n\n',
            )

        return Token(
            type=TokenType.LINE_BREAK,
            position=start_pos,
            value='\n',
        )

    def _scan_raw_text(self) -> Token:
        """
        扫描原始文本 — 直到遇到未转义的特殊字符或行尾。
        转义: \\* → * 字面量（跳过 \\，保留 * 在文本中）。
        """
        start = self.pos
        specials = {STAR, UNDERSCORE, TILDE, BACKTICK, BANG, LBRACKET, AT, '^', NEWLINE}
        end = self._line_end()

        while self.pos < end:
            ch = self.source[self.pos]
            # \\ 后跟特殊字符 → 跳过 \\，下一个字符作为普通文本
            if ch == '\\' and self.pos + 1 < len(self.source) and self.source[self.pos + 1] in specials:
                self._advance(2)  # 跳过 \\ 和特殊字符（均归为 raw text）
                continue
            if ch in specials:
                break
            self._advance(1)

        if self.pos == start:
            self._advance(1)
            return Token(
                type=TokenType.RAW_TEXT,
                position=Position(self.line, self.col - 1, start),
                value=self.source[start],
            )

        text = self.source[start:self.pos]
        return Token(
            type=TokenType.RAW_TEXT,
            position=Position(self.line, self.col - len(text), start),
            value=text,
        )

    # ================================================================
    # 辅助方法
    # ================================================================

    def _peek(self) -> Optional[str]:
        """查看当前字符，不前进"""
        if self.pos >= len(self.source):
            return None
        return self.source[self.pos]

    def _peek_at(self, index: int) -> Optional[str]:
        """查看指定位置的字符，不前进"""
        if index >= len(self.source):
            return None
        return self.source[index]

    def _advance(self, n: int = 1):
        """前进 n 个字符，更新行列信息"""
        for _ in range(n):
            if self.pos >= len(self.source):
                return
            ch = self.source[self.pos]
            self.pos += 1
            if ch == NEWLINE:
                self.line += 1
                self.col = 1
            else:
                self.col += 1

    def _line_end(self) -> int:
        """返回当前行的结束索引（不含换行符）"""
        end = self.source.find(NEWLINE, self.pos)
        if end == -1:
            return len(self.source)
        return end

    def _fallback_raw_text(self, start_pos: Position, text: str) -> Token:
        """回退到原始文本 Token（用于解析失败的情况）"""
        return Token(
            type=TokenType.RAW_TEXT,
            position=start_pos,
            value=text,
        )

    # ================================================================
    # 调试工具
    # ================================================================

    def dump_tokens(self, tokens: List[Token]) -> str:
        """格式化输出 Token 列表，便于调试"""
        lines = [f"{'='*60}",
                 f"Token Stream ({len(tokens)} tokens)",
                 f"{'='*60}"]
        for i, t in enumerate(tokens):
            meta_str = f" meta={t.metadata}" if t.metadata else ""
            lines.append(
                f"  [{i:03d}] {t.type.name:<18} "
                f"@ {str(t.position):>10}"
                f"  value='{t.value[:40]}'{meta_str}"
            )
        return '\n'.join(lines)
