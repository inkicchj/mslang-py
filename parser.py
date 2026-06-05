"""
mslang 语法解析器 (Parser)

将词法解析器输出的 Token 流构建为抽象语法树 (AST)。

架构：
  Token Stream → 块级分组 → 行内元素解析 → AST

处理流程：
  1. 遍历 Token 流，按 BLANK_LINE / LINE_BREAK 边界分组为块
  2. 每个块根据首 Token 类型确定其 AST 节点类型
  3. 对块内的 RAW_TEXT，调用内联解析器提取行内节点
  4. 组装最终 Document 节点
"""

from typing import List, Optional
from .tokens import Token, TokenType
from .lexer import parse_function_args
from .nodes import (
    Document,
    Heading, Paragraph, BlockQuote, CodeBlock,
    UnorderedList, OrderedList, ListItem, HorizontalRule,
    RawText, Bold, Italic, Strikethrough, InlineCode,
    Link, Image, LineBreak, FunctionCall, Color,
    Superscript, Subscript, RawHtml, FootnoteRef,
    Table, AlignBlock,
    InlineNode, BlockNode,
)


class ParserError(Exception):
    """语法解析错误"""
    def __init__(self, message: str, token: Optional[Token] = None):
        loc = f" [{token.position}]" if token else ""
        super().__init__(f"ParseError{loc}: {message}")
        self.token = token


class Parser:
    """
    mslang 语法解析器

    使用方式:
        parser = Parser()
        ast = parser.parse(tokens)          # Token 列表 → Document AST
        ast = parser.parse_text(source)     # 原始文本 → Document AST（内部调用 Lexer）
    """

    def __init__(self):
        self._tokens: List[Token] = []
        self._pos: int = 0
        self._footnote_defs: dict = {}  # {label: content} collected during parsing

    # ================================================================
    # 公共接口
    # ================================================================

    def parse(self, tokens: List[Token]) -> Document:
        """
        将 Token 列表解析为 Document AST。

        Args:
            tokens: Lexer.tokenize() 输出的 Token 列表

        Returns:
            Document: 文档 AST 根节点
        """
        self._tokens = tokens
        self._pos = 0
        self._footnote_defs = {}

        document = Document()

        while not self._is_at_end():
            block = self._parse_block()
            if block is not None:
                document.blocks.append(block)

        # 为脚注引用编号，并将定义存入 Document
        if self._footnote_defs:
            document.footnotes = dict(self._footnote_defs)
            self._number_footnotes(document)

        return document

    def parse_text(self, source: str) -> Document:
        """
        直接解析原始文本（内部调用 Lexer）。

        Args:
            source: mslang 格式原始文本

        Returns:
            Document: 文档 AST 根节点
        """
        from .lexer import Lexer
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        return self.parse(tokens)

    # ================================================================
    # 块级解析
    # ================================================================

    def _parse_block(self) -> Optional[BlockNode]:
        """解析下一个块级节点"""
        token = self._current()

        # 跳过行间空白
        if token.type == TokenType.LINE_BREAK:
            self._advance()
            return None

        # 段落分隔空白行：第一个 BLANK_LINE 作为块分隔符
        # 额外的连续 BLANK_LINE 产生可见间距
        if token.type == TokenType.BLANK_LINE:
            self._advance()
            extra_blanks = 0
            # 连续 BLANK_LINE → 计数
            while self._current() and self._current().type == TokenType.BLANK_LINE:
                self._advance()
                extra_blanks += 1
            # 奇数个 \n 的剩余 LINE_BREAK 也算一次间距
            if self._current() and self._current().type == TokenType.LINE_BREAK:
                self._advance()
                # 检查 LINE_BREAK 后是否还有更多 BLANK_LINE
                if self._current() and self._current().type == TokenType.BLANK_LINE:
                    extra_blanks += 1
                    self._advance()
                    # 消费后续连续的 BLANK_LINE
                    while self._current() and self._current().type == TokenType.BLANK_LINE:
                        self._advance()
                        extra_blanks += 1
                else:
                    extra_blanks += 1
            if extra_blanks > 0:
                # 每个额外空白行生成一个带 <br> 的段落
                return Paragraph(content=[LineBreak() for _ in range(extra_blanks)])
            return None

        # 标题
        if token.type == TokenType.HEADING:
            return self._parse_heading()

        # 分割线
        if token.type == TokenType.HORIZONTAL_RULE:
            self._advance()
            return HorizontalRule()

        # 引用块
        if token.type == TokenType.BLOCKQUOTE:
            return self._parse_blockquote()

        # 代码块
        if token.type == TokenType.CODE_BLOCK and \
           token.metadata and token.metadata.get('fence_type') == 'start':
            return self._parse_code_block()

        # 无序列表
        if token.type == TokenType.UNORDERED_LIST:
            return self._parse_unordered_list()

        # 有序列表
        if token.type == TokenType.ORDERED_LIST:
            return self._parse_ordered_list()

        # 表格
        if token.type == TokenType.TABLE_ROW:
            return self._parse_table()

        # 脚注定义
        if token.type == TokenType.FOOTNOTE_DEF:
            return self._parse_footnote_def()

        # 对齐
        if token.type in (TokenType.ALIGN_RIGHT, TokenType.ALIGN_CENTER):
            return self._parse_align(token)

        # 默认为段落
        if token.type in (TokenType.RAW_TEXT,) or \
           token.type.value >= TokenType.BOLD.value:
            return self._parse_paragraph()

        # 未知 Token
        self._advance()
        return None

    def _parse_heading(self) -> Heading:
        """解析标题"""
        token = self._advance()
        level = token.metadata.get('level', 1)
        heading_id = token.metadata.get('id', '')
        inlines = self._parse_inline(token.value)
        return Heading(level=level, content=inlines, id=heading_id)

    def _parse_paragraph(self) -> Paragraph:
        """解析段落"""
        inlines: List[InlineNode] = []
        seen_text = False

        while not self._is_at_end():
            token = self._current()

            # 段落结束条件
            if self._is_block_boundary(token):
                break

            if token.type == TokenType.LINE_BREAK:
                # 行结束
                self._advance()
                token = self._current()
                # 如果是块边界，结束段落
                if token and self._is_block_boundary(token):
                    break
                # 否则添加换行
                inlines.append(LineBreak())
                continue

            if token.type == TokenType.RAW_TEXT:
                text = token.value
                self._advance()
                inlines.extend(self._parse_inline(text))
                seen_text = True
                continue

            # 行内 Token
            inline = self._parse_inline_token()
            if inline:
                inlines.append(inline)
                seen_text = True
            else:
                self._advance()

        if not seen_text:
            return Paragraph(content=[RawText('')])

        return Paragraph(content=self._merge_adjacent_text(inlines))

    def _parse_blockquote(self) -> BlockQuote:
        """解析引用块"""
        inlines: List[InlineNode] = []

        while not self._is_at_end():
            token = self._current()

            if token.type == TokenType.BLOCKQUOTE:
                self._advance()
                inlines.extend(self._parse_inline(token.value))
                continue

            if token.type == TokenType.LINE_BREAK:
                self._advance()
                next_t = self._current()
                if next_t and next_t.type == TokenType.BLOCKQUOTE:
                    inlines.append(LineBreak())
                    continue
                break

            if token.type == TokenType.BLANK_LINE:
                # 不消费 BLANK_LINE，留给外层 _parse_block 处理间距
                break

            break

        return BlockQuote(content=self._merge_adjacent_text(inlines))

    def _parse_code_block(self) -> CodeBlock:
        """解析代码块"""
        start_token = self._advance()
        language = start_token.metadata.get('language', '')
        code_lines: List[str] = []

        while not self._is_at_end():
            token = self._current()

            # 代码块结束标记
            if token.type == TokenType.CODE_BLOCK and \
               token.metadata and token.metadata.get('fence_type') == 'end':
                self._advance()
                break

            if token.type == TokenType.RAW_TEXT and \
               token.metadata and token.metadata.get('in_code_block'):
                code_lines.append(token.value)
                self._advance()
                continue

            # LINE_BREAK 已在 RAW_TEXT 的行间和 \n.join 中隐含，跳过
            if token.type == TokenType.LINE_BREAK:
                self._advance()
                continue

            # 防止死循环
            self._advance()

        # 去除代码块首尾空行
        while code_lines and code_lines[0] == '':
            code_lines.pop(0)
        while code_lines and code_lines[-1] == '':
            code_lines.pop()
        code = '\n'.join(code_lines)
        return CodeBlock(language=language, code=code)

    def _parse_unordered_list(self) -> UnorderedList:
        """解析无序列表（支持嵌套）"""
        return UnorderedList(items=self._parse_list_items(TokenType.UNORDERED_LIST))

    def _parse_ordered_list(self) -> OrderedList:
        """解析有序列表（支持嵌套）"""
        return OrderedList(items=self._parse_list_items(TokenType.ORDERED_LIST))

    def _parse_list_items(self, list_type: TokenType) -> List[ListItem]:
        """解析列表项（支持嵌套子列表）"""
        items: List[ListItem] = []
        # 跳过开头的 LINE_BREAK
        while self._current() and self._current().type == TokenType.LINE_BREAK:
            self._advance()
        first_token = self._current()
        base_indent = first_token.metadata.get('indent', 0) if (first_token and first_token.metadata) else 0

        while not self._is_at_end():
            token = self._current()

            if token.type == list_type:
                token_indent = token.metadata.get('indent', 0)
                if token_indent < base_indent:
                    break
                self._advance()
                inlines = self._parse_inline(token.value)
                item = ListItem(content=self._merge_adjacent_text(inlines))

                # 检测任务列表标记 [ ] 或 [x]
                if item.content and isinstance(item.content[0], RawText):
                    t = item.content[0].text
                    if t.startswith('[ ] '):
                        item.checked = False
                        item.content[0] = RawText(text=t[4:])
                    elif t.startswith('[x] ') or t.startswith('[X] '):
                        item.checked = True
                        item.content[0] = RawText(text=t[4:])

                # 检查是否有嵌套子列表（跳过 LINE_BREAK）
                next_t = self._peek_past_breaks()
                if next_t and next_t.type in (TokenType.UNORDERED_LIST, TokenType.ORDERED_LIST):
                    next_indent = next_t.metadata.get('indent', 0) if next_t.metadata else 0
                    if next_indent > base_indent:
                        if next_t.type == TokenType.UNORDERED_LIST:
                            item.children = [UnorderedList(items=self._parse_list_items(TokenType.UNORDERED_LIST))]
                        else:
                            item.children = [OrderedList(items=self._parse_list_items(TokenType.ORDERED_LIST))]

                items.append(item)
                continue

            if token.type == TokenType.LINE_BREAK:
                self._advance()
                next_token = self._current()
                if next_token and next_token.type == list_type:
                    continue
                else:
                    break

            if token.type == TokenType.BLANK_LINE:
                break

            break

        return items

    # ================================================================
    # 行内解析
    # ================================================================

    def _parse_table(self) -> Table:
        """解析表格"""
        headers = []
        rows = []
        has_sep = False

        while not self._is_at_end():
            token = self._current()
            if token.type != TokenType.TABLE_ROW and token.type != TokenType.TABLE_SEP:
                break

            cells = token.metadata.get('cells', []) if token.metadata else []
            self._advance()

            if token.type == TokenType.TABLE_SEP:
                has_sep = True
                # skip LINE_BREAK after separator
                if self._current() and self._current().type == TokenType.LINE_BREAK:
                    self._advance()
                continue

            if not has_sep:
                headers = cells
            else:
                rows.append(cells)

            # skip LINE_BREAK
            if self._current() and self._current().type == TokenType.LINE_BREAK:
                self._advance()

        return Table(headers=headers, rows=rows)

    def _number_footnotes(self, doc: Document):
        """递归遍历 AST，为脚注引用分配序号"""
        counter = [0]  # mutable counter
        def walk(node):
            if isinstance(node, FootnoteRef):
                counter[0] += 1
                node.number = counter[0]
            for attr in ('content', 'children', 'blocks', 'items'):
                children = getattr(node, attr, None)
                if isinstance(children, list):
                    for child in children:
                        walk(child)
        for block in doc.blocks:
            walk(block)

    def _parse_footnote_def(self):
        """解析脚注定义，存入内部字典"""
        token = self._advance()
        label = token.metadata.get('label', '')
        self._footnote_defs[label] = token.value
        return None

    def _parse_align(self, token: Token) -> AlignBlock:
        """解析对齐块"""
        self._advance()
        align = 'right' if token.type == TokenType.ALIGN_RIGHT else 'center'
        inlines = self._parse_inline(token.value)
        return AlignBlock(align=align, content=self._merge_adjacent_text(inlines))

    def _parse_inline_token(self) -> Optional[InlineNode]:
        """解析当前 Token 为行内节点"""
        token = self._current()

        if token.type == TokenType.BOLD:
            self._advance()
            return Bold(content=self._parse_inline(token.value))

        if token.type == TokenType.ITALIC:
            self._advance()
            return Italic(content=self._parse_inline(token.value))

        if token.type == TokenType.STRIKETHROUGH:
            self._advance()
            return Strikethrough(content=self._parse_inline(token.value))

        if token.type == TokenType.INLINE_CODE:
            self._advance()
            return InlineCode(code=token.value)

        if token.type == TokenType.LINK:
            self._advance()
            return Link(text=token.value, url=token.metadata.get('url', ''))

        if token.type == TokenType.IMAGE:
            self._advance()
            return Image(
                alt=token.value,
                url=token.metadata.get('url', ''),
                width=token.metadata.get('width', ''),
            )

        if token.type == TokenType.FUNCTION_CALL:
            self._advance()
            return FunctionCall(
                name=token.value,
                args=token.metadata.get('args', []),
                kwargs=token.metadata.get('kwargs', {}),
                raw_args=token.metadata.get('raw_args', ''),
            )

        if token.type == TokenType.COLOR:
            self._advance()
            return Color(
                color=token.metadata.get('color', ''),
                text=token.value,
            )

        if token.type == TokenType.SUPERSCRIPT:
            self._advance()
            return Superscript(content=self._parse_inline(token.value))

        if token.type == TokenType.SUBSCRIPT:
            self._advance()
            return Subscript(content=self._parse_inline(token.value))

        if token.type == TokenType.FOOTNOTE_REF:
            self._advance()
            return FootnoteRef(label=token.value)

        return None

    def _parse_inline(self, text: str) -> List[InlineNode]:
        """
        解析一个纯文本字符串中的行内元素。

        对文本进行二次词法/解析扫描，提取其中的加粗、斜体等行内格式。
        """
        if not text:
            return []

        inlines: List[InlineNode] = []
        i = 0
        while i < len(text):
            # 尝试匹配行内模式
            matched = False

            # **bold**
            if text.startswith('**', i):
                end = text.find('**', i + 2)
                if end != -1:
                    inner = text[i + 2:end]
                    inlines.append(Bold(content=self._parse_inline(inner)))
                    i = end + 2
                    matched = True

            # __bold__
            elif text.startswith('__', i):
                end = text.find('__', i + 2)
                if end != -1:
                    inner = text[i + 2:end]
                    inlines.append(Bold(content=self._parse_inline(inner)))
                    i = end + 2
                    matched = True

            # *italic* (but not **)
            elif text[i] == '*' and not text.startswith('**', i):
                end = text.find('*', i + 1)
                if end != -1:
                    inner = text[i + 1:end]
                    inlines.append(Italic(content=self._parse_inline(inner)))
                    i = end + 1
                    matched = True

            # _italic_ (but not __)
            elif text[i] == '_' and not text.startswith('__', i):
                end = text.find('_', i + 1)
                if end != -1:
                    inner = text[i + 1:end]
                    inlines.append(Italic(content=self._parse_inline(inner)))
                    i = end + 1
                    matched = True

            # ~~strikethrough~~
            elif text.startswith('~~', i):
                end = text.find('~~', i + 2)
                if end != -1:
                    inner = text[i + 2:end]
                    inlines.append(Strikethrough(content=self._parse_inline(inner)))
                    i = end + 2
                    matched = True

            # ~subscript~ (not ~~)
            elif text[i] == '~' and not text.startswith('~~', i):
                end = text.find('~', i + 1)
                if end != -1 and end > i + 1:
                    inner = text[i + 1:end]
                    inlines.append(Subscript(content=self._parse_inline(inner)))
                    i = end + 1
                    matched = True

            # ^superscript^
            elif text[i] == '^':
                end = text.find('^', i + 1)
                if end != -1 and end > i + 1:
                    inner = text[i + 1:end]
                    inlines.append(Superscript(content=self._parse_inline(inner)))
                    i = end + 1
                    matched = True

            # `inline code`
            elif text[i] == '`':
                end = text.find('`', i + 1)
                if end != -1:
                    code = text[i + 1:end]
                    inlines.append(InlineCode(code=code))
                    i = end + 1
                    matched = True

            # [link](url)
            elif text[i] == '[':
                # 脚注引用 [^label]
                if i + 1 < len(text) and text[i + 1] == '^':
                    end = text.find(']', i + 2)
                    if end != -1:
                        label = text[i + 2:end]
                        inlines.append(FootnoteRef(label=label))
                        i = end + 1
                        matched = True
                else:
                    text_end = text.find(']', i + 1)
                    if text_end != -1 and text_end + 1 < len(text) and text[text_end + 1] == '(':
                        url_end = text.find(')', text_end + 2)
                        if url_end != -1:
                            link_text = text[i + 1:text_end]
                            url = text[text_end + 2:url_end]
                            inlines.append(Link(text=link_text, url=url))
                            i = url_end + 1
                            matched = True

            # ![image](url) 或 ![image](url 80%)
            elif text.startswith('![', i):
                alt_end = text.find(']', i + 2)
                if alt_end != -1 and alt_end + 1 < len(text) and text[alt_end + 1] == '(':
                    url_end = text.find(')', alt_end + 2)
                    if url_end != -1:
                        alt = text[i + 2:alt_end]
                        url_raw = text[alt_end + 2:url_end].strip()
                        url = url_raw
                        width = ''
                        if ' ' in url_raw:
                            parts = url_raw.rsplit(' ', 1)
                            if parts[1].endswith('%') and parts[1][:-1].isdigit():
                                url = parts[0]
                                width = parts[1]
                        inlines.append(Image(alt=alt, url=url, width=width))
                        i = url_end + 1
                        matched = True

            # @function(args)
            elif text[i] == '@':
                j = i + 1
                while j < len(text) and (text[j].isalnum() or text[j] == '_'):
                    j += 1
                if j > i + 1 and j < len(text) and text[j] == '(':
                    rp = text.find(')', j + 1)
                    if rp != -1:
                        name = text[i + 1:j]
                        raw_args = text[j + 1:rp]
                        args, kwargs_ = parse_function_args(raw_args)
                        inlines.append(FunctionCall(
                            name=name, args=args, kwargs=kwargs_,
                            raw_args=raw_args,
                        ))
                        i = rp + 1
                        matched = True

            # /#hex:text:/
            elif text.startswith('/#', i):
                j = i + 2
                while j < len(text) and text[j] in '0123456789abcdefABCDEF':
                    j += 1
                hex_len = j - i - 2
                if hex_len in (3, 6) and j < len(text) and text[j] == ':':
                    end = text.find(':/', j + 1)
                    if end != -1:
                        color = text[i+2:j]
                        inner = text[j+1:end]
                        inlines.append(Color(color=color, text=inner))
                        i = end + 2
                        matched = True

            # 转义: \* → * 字面量
            if not matched and text[i] == '\\':
                specials = {'*', '_', '~', '`', '[', '!', '@', '/', '\\'}
                if i + 1 < len(text) and text[i + 1] in specials:
                    inlines.append(RawText(text=text[i + 1]))
                    i += 2
                    matched = True

            # HTML 透传: <tag>...</tag> 或 <tag/>
            if not matched and text[i] == '<':
                end = text.find('>', i + 1)
                if end != -1:
                    inlines.append(RawHtml(html=text[i:end + 1]))
                    i = end + 1
                    matched = True

            if not matched:
                # 收集连续普通文本
                j = i + 1
                specials = {'*', '_', '~', '`', '[', '!', '@', '\\', '^', '<'}
                while j < len(text) and text[j] not in specials:
                    j += 1
                inlines.append(RawText(text=text[i:j]))
                i = j

        return self._merge_adjacent_text(self._autolink(inlines))

    def _merge_adjacent_text(self, nodes: List[InlineNode]) -> List[InlineNode]:
        """合并相邻的 RawText 节点"""
        if not nodes:
            return nodes
        merged: List[InlineNode] = []
        for node in nodes:
            if merged and isinstance(merged[-1], RawText) and isinstance(node, RawText):
                merged[-1] = RawText(text=merged[-1].text + node.text)
            else:
                merged.append(node)
        return merged

    import re as _re
    _URL_RE = _re.compile(r'^(https?://[^\s<>"{}|\\^`]+)$')       # 全串 URL
    _URL_FIND_RE = _re.compile(r'https?://[^\s<>"{}|\\^`]+')      # 嵌入 URL

    def _autolink(self, nodes: List[InlineNode]) -> List[InlineNode]:
        """检测 RawText 中的裸 URL 并转为 Link，支持嵌入文本中的 URL"""
        result = []
        for node in nodes:
            if not isinstance(node, RawText):
                result.append(node)
                continue

            text = node.text
            if not text:
                result.append(node)
                continue

            # 快速路径：整条文本就是 URL
            if self._URL_RE.match(text):
                result.append(Link(text=text, url=text))
                continue

            # 在文本中搜索嵌入的 URL
            last_idx = 0
            found = False
            for m in self._URL_FIND_RE.finditer(text):
                found = True
                # URL 前的普通文本
                if m.start() > last_idx:
                    result.append(RawText(text=text[last_idx:m.start()]))
                # URL 转为 Link
                result.append(Link(text=m.group(), url=m.group()))
                last_idx = m.end()

            if not found:
                result.append(node)
            elif last_idx < len(text):
                # URL 后的剩余文本
                result.append(RawText(text=text[last_idx:]))
        return result

    # ================================================================
    # 辅助方法
    # ================================================================

    def _current(self) -> Optional[Token]:
        """返回当前 Token"""
        if self._pos < len(self._tokens):
            return self._tokens[self._pos]
        return None

    def _advance(self) -> Token:
        """消费并返回当前 Token，前进一位"""
        token = self._tokens[self._pos]
        self._pos += 1
        return token

    def _peek_past_breaks(self, offset: int = 0):
        """向前查看，跳过 LINE_BREAK"""
        p = self._pos + offset
        while p < len(self._tokens) and self._tokens[p].type == TokenType.LINE_BREAK:
            p += 1
        if p < len(self._tokens):
            return self._tokens[p]
        return None

    def _is_at_end(self) -> bool:
        """是否到达 Token 流末尾（EOF）"""
        if self._pos >= len(self._tokens):
            return True
        return self._tokens[self._pos].type == TokenType.EOF

    def _is_block_boundary(self, token: Token) -> bool:
        """判断 Token 是否为块级边界"""
        return token.type in (
            TokenType.HEADING,
            TokenType.HORIZONTAL_RULE,
            TokenType.BLOCKQUOTE,
            TokenType.UNORDERED_LIST,
            TokenType.ORDERED_LIST,
            TokenType.TABLE_ROW, TokenType.TABLE_SEP,
            TokenType.ALIGN_RIGHT, TokenType.ALIGN_CENTER,
            TokenType.BLANK_LINE,
            TokenType.EOF,
        ) or (
            token.type == TokenType.CODE_BLOCK and
            token.metadata and
            token.metadata.get('fence_type') in ('start', 'end')
        )

    def dump_ast(self, node, indent: int = 0, prefix: str = '',
                  is_last: bool = True) -> str:
        """
        格式化打印完整 AST 语法树，用于调试。

        使用树状缩进符（├── └── │）展示完整的递归层级结构，
        所有行内节点、属性、嵌套关系全部展开。
        """
        return dump_ast(node, indent, prefix, is_last)


# ================================================================
# 模块级 AST 打印函数（可独立使用）
# ================================================================

def dump_ast(node, indent: int = 0, prefix: str = '',
             is_last: bool = True) -> str:
    """
    以树状结构打印完整 AST。

    用法:
        from mslang.parser import dump_ast
        print(dump_ast(ast))

    输出格式:
        Document
        ├── Heading (level=1)
        │   └── Text "标题文本"
        ├── Paragraph
        │   ├── Text "这是 "
        │   ├── Bold
        │   │   └── Text "加粗"
        │   └── Text " 文本"
        └── HorizontalRule
    """
    connector = '└── ' if is_last else '├── '
    continuation = '    ' if is_last else '│   '

    # 第一层不用 connector
    if indent == 0:
        line_prefix = ''
    else:
        line_prefix = prefix + connector

    name = type(node).__name__

    # === 文档根 ===
    if isinstance(node, Document):
        lines = ['Document']
        blocks = node.blocks
        for i, block in enumerate(blocks):
            last = (i == len(blocks) - 1)
            lines.append(dump_ast(block, indent + 1, '', last))
        return '\n'.join(lines)

    # === 块级节点 ===
    if isinstance(node, Heading):
        lines = [f'{line_prefix}Heading (level={node.level})']
        lines.extend(_dump_inlines(node.content, indent + 1, continuation))
        return '\n'.join(lines)

    if isinstance(node, Paragraph):
        if _is_spacer(node):
            return f'{line_prefix}Spacer (x{len(node.content)} <br>)'
        lines = [f'{line_prefix}Paragraph']
        lines.extend(_dump_inlines(node.content, indent + 1, continuation))
        return '\n'.join(lines)

    if isinstance(node, BlockQuote):
        lines = [f'{line_prefix}BlockQuote']
        lines.extend(_dump_inlines(node.content, indent + 1, continuation))
        return '\n'.join(lines)

    if isinstance(node, CodeBlock):
        lines = [f'{line_prefix}CodeBlock (lang={node.language!r})']
        code_preview = node.code.strip()
        for code_line in code_preview.split('\n'):
            lines.append(f'{continuation}│   {code_line}')
        return '\n'.join(lines)

    if isinstance(node, UnorderedList):
        lines = [f'{line_prefix}UnorderedList']
        for i, item in enumerate(node.items):
            last = (i == len(node.items) - 1)
            lines.append(dump_ast(item, indent + 1, continuation, last))
        return '\n'.join(lines)

    if isinstance(node, OrderedList):
        lines = [f'{line_prefix}OrderedList']
        for i, item in enumerate(node.items):
            last = (i == len(node.items) - 1)
            lines.append(dump_ast(item, indent + 1, continuation, last))
        return '\n'.join(lines)

    if isinstance(node, ListItem):
        lines = [f'{line_prefix}ListItem']
        lines.extend(_dump_inlines(node.content, indent + 1, continuation))
        return '\n'.join(lines)

    if isinstance(node, HorizontalRule):
        return f'{line_prefix}HorizontalRule'

    if isinstance(node, AlignBlock):
        lines = [f'{line_prefix}AlignBlock ({node.align})']
        lines.extend(_dump_inlines(node.content, indent + 1, continuation))
        return '\n'.join(lines)

    # === 行内节点 ===
    if isinstance(node, FunctionCall):
        args_repr = node.raw_args if node.raw_args else ''
        return f'{line_prefix}FunctionCall @{node.name}({args_repr})'

    if isinstance(node, Color):
        return f'{line_prefix}Color #{node.color} "{node.text}"'

    if isinstance(node, Superscript):
        lines = [f'{line_prefix}Superscript']
        lines.extend(_dump_inlines(node.content, indent + 1, continuation))
        return '\n'.join(lines)

    if isinstance(node, Subscript):
        lines = [f'{line_prefix}Subscript']
        lines.extend(_dump_inlines(node.content, indent + 1, continuation))
        return '\n'.join(lines)

    if isinstance(node, RawHtml):
        return f'{line_prefix}RawHtml {node.html}'

    if isinstance(node, FootnoteRef):
        return f'{line_prefix}FootnoteRef [{node.label}] #{node.number}'

    if isinstance(node, Bold):
        lines = [f'{line_prefix}Bold']
        lines.extend(_dump_inlines(node.content, indent + 1, continuation))
        return '\n'.join(lines)

    if isinstance(node, Italic):
        lines = [f'{line_prefix}Italic']
        lines.extend(_dump_inlines(node.content, indent + 1, continuation))
        return '\n'.join(lines)

    if isinstance(node, Strikethrough):
        lines = [f'{line_prefix}Strikethrough']
        lines.extend(_dump_inlines(node.content, indent + 1, continuation))
        return '\n'.join(lines)

    if isinstance(node, InlineCode):
        return f'{line_prefix}InlineCode `{node.code}`'

    if isinstance(node, Link):
        return f'{line_prefix}Link "{node.text}" -> {node.url}'

    if isinstance(node, Image):
        return f'{line_prefix}Image alt="{node.alt}" src="{node.url}"'

    if isinstance(node, RawText):
        return f'{line_prefix}Text "{node.text}"'

    if isinstance(node, LineBreak):
        return f'{line_prefix}LineBreak'

    return f'{line_prefix}{name}'


def _is_spacer(node) -> bool:
    """判断是否是纯空行段落（只有 LineBreak）"""
    return (
        isinstance(node, Paragraph) and
        node.content and
        all(isinstance(n, LineBreak) for n in node.content)
    )


def _dump_inlines(nodes, indent, prefix) -> list:
    """渲染行内节点列表为树状行"""
    lines = []
    for i, n in enumerate(nodes):
        last = (i == len(nodes) - 1)
        lines.append(dump_ast(n, indent, prefix, last))
    return lines
