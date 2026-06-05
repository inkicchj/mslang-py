"""
mslang 渲染引擎 (Renderer)

将 AST 渲染为目标格式。采用 Visitor 模式遍历 AST 树。
输出纯 HTML 片段（无 class 属性），外层包 <div> 便于 CSS 选择器定位。
"""

import html as html_module
from typing import Dict, List, Callable, Union
from .nodes import (
    NodeVisitor, ASTNode,
    Document, Heading, Paragraph, BlockQuote, CodeBlock,
    UnorderedList, OrderedList, ListItem, HorizontalRule,
    RawText, Bold, Italic, Strikethrough, InlineCode,
    Link, Image, LineBreak, FunctionCall, Color,
    Superscript, Subscript, RawHtml, Table, FootnoteRef, AlignBlock,
)


class HTMLRenderer(NodeVisitor):
    """
    AST → HTML 渲染器，输出不含 class 属性的纯 HTML 片段。

    使用:
        renderer = HTMLRenderer()
        html = renderer.render(source)                       # <div class="mslang"><p>text</p></div>
        html = renderer.render(source, wrapper_class='doc')  # <div class="doc">...
        html = renderer.render(source, wrapper_id='main')    # <div id="main">...
    """

    def __init__(self, pretty: bool = True, escape_html: bool = True,
                 functions: Dict[str, Callable] = None):
        self.pretty = pretty
        self.escape_html = escape_html
        self._functions: Dict[str, Callable] = functions or {}
        self._output: List[str] = []

    def add_function(self, name: str, func: Callable):
        """注册自定义函数"""
        self._functions[name] = func

    def function(self, name: str = None):
        """装饰器方式注册"""
        def decorator(func: Callable):
            fn_name = name or func.__name__
            self._functions[fn_name] = func
            return func
        return decorator

    def render(self, source: Union[str, Document], *,
               wrapper_class: str = 'mslang',
               wrapper_id: str = '') -> str:
        """渲染为 HTML 片段，外层用 <div> 包裹。

        Args:
            source: mslang 文本或 Document AST
            wrapper_class: 外层 div 的 class 属性
            wrapper_id: 外层 div 的 id 属性
        """
        if isinstance(source, Document):
            self._output = []
            source.accept(self)
            body = ''.join(self._output)
        else:
            from .lexer import Lexer
            from .parser import Parser
            tokens = Lexer(source).tokenize()
            ast = Parser().parse(tokens)
            self._output = []
            ast.accept(self)
            body = ''.join(self._output)

        cls = f' class="{wrapper_class}"' if wrapper_class else ''
        id_ = f' id="{wrapper_id}"' if wrapper_id else ''
        return f'<div{cls}{id_}>\n{body}\n</div>'

    # ================================================================
    # Visitor 实现 — 文档根
    # ================================================================

    def generic_visit(self, node: ASTNode):
        """默认访问回退"""
        self._write(f'<!-- unhandled: {type(node).__name__} -->')

    def visit_Document(self, doc: Document):
        for i, block in enumerate(doc.blocks):
            block.accept(self)
            if self.pretty and i < len(doc.blocks) - 1:
                self._write('\n')
        # 脚注区域
        if doc.footnotes:
            if self.pretty:
                self._write('\n')
            self._write('<hr>')
            if self.pretty: self._write('\n')
            self._write('<ol>')
            if self.pretty: self._write('\n')
            # 按 label 顺序列出
            for idx, (label, text) in enumerate(doc.footnotes.items(), 1):
                self._write(f'<li id="fn-{idx}">{self._esc(text)} '
                            f'<a href="#fnref-{idx}">&#8617;</a></li>')
                if self.pretty: self._write('\n')
            self._write('</ol>')
            if self.pretty: self._write('\n')

    # ================================================================
    # Visitor 实现 — 块级
    # ================================================================

    def visit_Heading(self, node: Heading):
        tag = f'h{min(node.level, 6)}'
        id_attr = f' id="{node.id}"' if node.id else ''
        self._write(f'<{tag}{id_attr}>')
        for n in node.content: n.accept(self)
        self._write(f'</{tag}>')
        if self.pretty:
            self._write('\n')

    def visit_Paragraph(self, node: Paragraph):
        if node.content and all(isinstance(n, LineBreak) for n in node.content):
            for _ in node.content:
                self._write('<br>')
                if self.pretty:
                    self._write('\n')
            return
        self._write('<p>')
        for n in node.content: n.accept(self)
        self._write('</p>')
        if self.pretty:
            self._write('\n')

    def visit_BlockQuote(self, node: BlockQuote):
        self._write('<blockquote>')
        if self.pretty: self._write('\n')
        for n in node.content: n.accept(self)
        if self.pretty: self._write('\n')
        self._write('</blockquote>')
        if self.pretty: self._write('\n')

    def visit_CodeBlock(self, node: CodeBlock):
        lang_attr = f' data-language="{self._esc(node.language)}"' if node.language else ''
        self._write(f'<pre{lang_attr}><code>')
        self._write(self._esc(node.code))
        self._write('</code></pre>')
        if self.pretty: self._write('\n')

    def visit_UnorderedList(self, node: UnorderedList):
        self._write('<ul>')
        if self.pretty: self._write('\n')
        for item in node.items: item.accept(self)
        self._write('</ul>')
        if self.pretty: self._write('\n')

    def visit_OrderedList(self, node: OrderedList):
        self._write('<ol>')
        if self.pretty: self._write('\n')
        for item in node.items: item.accept(self)
        self._write('</ol>')
        if self.pretty: self._write('\n')

    def visit_ListItem(self, node: ListItem):
        self._write('<li>')
        if node.checked is not None:
            checked = ' checked' if node.checked else ''
            self._write(f'<input type="checkbox" disabled{checked}>')
            self._write('<label>')
        for n in node.content: n.accept(self)
        for child in node.children: child.accept(self)
        if node.checked is not None:
            self._write('</label>')
        self._write('</li>')
        if self.pretty: self._write('\n')

    def visit_HorizontalRule(self, node: HorizontalRule):
        self._write('<hr>')
        if self.pretty: self._write('\n')

    def visit_AlignBlock(self, node: AlignBlock):
        style = 'text-align:' + node.align
        self._write(f'<div style="{style}">')
        for n in node.content: n.accept(self)
        self._write('</div>')
        if self.pretty: self._write('\n')

    def visit_Table(self, node: Table):
        self._write('<table>')
        if self.pretty: self._write('\n')
        if node.headers:
            self._write('<thead><tr>')
            for h in node.headers: self._write(f'<th>{self._esc(h)}</th>')
            self._write('</tr></thead>')
            if self.pretty: self._write('\n')
        if node.rows:
            self._write('<tbody>')
            if self.pretty: self._write('\n')
            for row in node.rows:
                self._write('<tr>')
                for cell in row: self._write(f'<td>{self._esc(cell)}</td>')
                self._write('</tr>')
                if self.pretty: self._write('\n')
            self._write('</tbody>')
            if self.pretty: self._write('\n')
        self._write('</table>')
        if self.pretty: self._write('\n')

    # ================================================================
    # Visitor 实现 — 行内
    # ================================================================

    def visit_RawText(self, node: RawText):
        """原始文本"""
        self._write(self._esc(node.text))

    def visit_Bold(self, node: Bold):
        self._write('<strong>')
        for n in node.content: n.accept(self)
        self._write('</strong>')

    def visit_Italic(self, node: Italic):
        self._write('<em>')
        for n in node.content: n.accept(self)
        self._write('</em>')

    def visit_Strikethrough(self, node: Strikethrough):
        self._write('<del>')
        for n in node.content: n.accept(self)
        self._write('</del>')

    def visit_InlineCode(self, node: InlineCode):
        self._write(f'<code>{self._esc(node.code)}</code>')

    def visit_Link(self, node: Link):
        self._write(f'<a href="{self._esc_attr(node.url)}">{self._esc(node.text)}</a>')

    def visit_Image(self, node: Image):
        w = f' width="{node.width}"' if node.width else ''
        self._write(f'<img src="{self._esc_attr(node.url)}" alt="{self._esc_attr(node.alt)}"{w}>')

    def visit_LineBreak(self, node: LineBreak):
        """换行"""
        self._write('<br>')

    def visit_FunctionCall(self, node: FunctionCall):
        """自定义函数调用"""
        func = self._functions.get(node.name)
        if func is None:
            # 未注册的函数：输出占位提示
            self._write(f'<!-- mslang: unknown function @{node.name} -->')
            return
        try:
            result = func(*node.args, **node.kwargs)
        except Exception as e:
            self._write(f'<!-- mslang: function @{node.name} error: {self._esc(str(e))} -->')
            return
        # 函数返回字符串 → 直接写入（不转义，允许返回 HTML）
        if isinstance(result, str):
            self._write(result)
        elif isinstance(result, list):
            # 返回 InlineNode 列表
            for item in result:
                if isinstance(item, str):
                    self._write(self._esc(item))
                elif hasattr(item, 'accept'):
                    item.accept(self)
        else:
            self._write(self._esc(str(result)))

    def visit_Color(self, node: Color):
        self._write(f'<span style="color:#{node.color}">{self._esc(node.text)}</span>')

    def visit_Superscript(self, node: Superscript):
        self._write('<sup>')
        for n in node.content: n.accept(self)
        self._write('</sup>')

    def visit_Subscript(self, node: Subscript):
        self._write('<sub>')
        for n in node.content: n.accept(self)
        self._write('</sub>')

    def visit_RawHtml(self, node: RawHtml):
        self._write(node.html)

    def visit_FootnoteRef(self, node: FootnoteRef):
        self._write(f'<sup><a href="#fn-{node.number}" id="fnref-{node.number}">'
                    f'[{node.number}]</a></sup>')

    # ================================================================
    # 辅助方法
    # ================================================================

    def _write(self, text: str):
        """写入输出缓冲区"""
        self._output.append(text)

    def _esc(self, text: str) -> str:
        """HTML 转义文本内容"""
        if self.escape_html:
            return html_module.escape(text, quote=False)
        return text

    def _esc_attr(self, text: str) -> str:
        if self.escape_html:
            return html_module.escape(text, quote=True)
        return text
