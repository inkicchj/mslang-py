"""
mslang AST 节点定义

语法解析器将 Token 流构建为抽象语法树（AST）。
每个节点类型对应一种文档结构元素。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


# ============================================================
# 抽象基类
# ============================================================

class ASTNode(ABC):
    """AST 节点抽象基类"""

    @abstractmethod
    def accept(self, visitor: 'NodeVisitor'):
        """接受访问者（Visitor 模式），用于渲染等遍历操作"""
        pass


class NodeVisitor(ABC):
    """AST 访问者抽象基类（Visitor 模式）"""

    @abstractmethod
    def generic_visit(self, node: ASTNode):
        pass


# ============================================================
# 文档根节点
# ============================================================

@dataclass
class Document(ASTNode):
    """文档根节点"""
    blocks: List['BlockNode'] = field(default_factory=list)
    footnotes: dict = field(default_factory=dict)  # {label: definition_text}

    def accept(self, visitor: NodeVisitor):
        return visitor.visit_Document(self)

    def __repr__(self):
        return f"Document(blocks={len(self.blocks)}, footnotes={len(self.footnotes)})"


# ============================================================
# 块级节点
# ============================================================

class BlockNode(ASTNode, ABC):
    """所有块级节点的抽象基类"""
    pass


@dataclass
class Heading(BlockNode):
    """标题节点: # ~ ######，支持 {#id}"""
    level: int
    content: List['InlineNode'] = field(default_factory=list)
    id: str = ""

    def accept(self, visitor: NodeVisitor):
        return visitor.visit_Heading(self)

    def __repr__(self):
        id_ = f', id={self.id}' if self.id else ''
        return f"Heading(level={self.level}{id_}, inlines={len(self.content)})"


@dataclass
class Paragraph(BlockNode):
    """段落节点：由空行分隔的文本块"""
    content: List['InlineNode'] = field(default_factory=list)

    def accept(self, visitor: NodeVisitor):
        return visitor.visit_Paragraph(self)

    def __repr__(self):
        return f"Paragraph(inlines={len(self.content)})"


@dataclass
class BlockQuote(BlockNode):
    """引用块节点: > text"""
    content: List['InlineNode'] = field(default_factory=list)

    def accept(self, visitor: NodeVisitor):
        return visitor.visit_BlockQuote(self)

    def __repr__(self):
        return f"BlockQuote(inlines={len(self.content)})"


@dataclass
class CodeBlock(BlockNode):
    """代码块节点: ```lang ... ```"""
    language: str = ""
    code: str = ""

    def accept(self, visitor: NodeVisitor):
        return visitor.visit_CodeBlock(self)

    def __repr__(self):
        return f"CodeBlock(lang='{self.language}', lines={len(self.code.splitlines())})"


@dataclass
class UnorderedList(BlockNode):
    """无序列表节点: - item / * item / + item"""
    items: List['ListItem'] = field(default_factory=list)

    def accept(self, visitor: NodeVisitor):
        return visitor.visit_UnorderedList(self)

    def __repr__(self):
        return f"UnorderedList(items={len(self.items)})"


@dataclass
class OrderedList(BlockNode):
    """有序列表节点: 1. item / 2. item"""
    items: List['ListItem'] = field(default_factory=list)

    def accept(self, visitor: NodeVisitor):
        return visitor.visit_OrderedList(self)

    def __repr__(self):
        return f"OrderedList(items={len(self.items)})"


@dataclass
class ListItem(ASTNode):
    """列表项节点"""
    content: List['InlineNode'] = field(default_factory=list)
    children: List['BlockNode'] = field(default_factory=list)
    checked: Optional[bool] = None   # None=普通, True=已勾选, False=未勾选

    def accept(self, visitor: NodeVisitor):
        return visitor.visit_ListItem(self)

    def __repr__(self):
        return f"ListItem(inlines={len(self.content)}, children={len(self.children)})"


@dataclass
class HorizontalRule(BlockNode):
    """分割线节点: --- / *** / ___"""

    def accept(self, visitor: NodeVisitor):
        return visitor.visit_HorizontalRule(self)

    def __repr__(self):
        return "HorizontalRule()"


@dataclass
class AlignBlock(BlockNode):
    """对齐块: >> right / -><- center"""
    align: str = "left"     # left | center | right
    content: List['InlineNode'] = field(default_factory=list)

    def accept(self, visitor: NodeVisitor):
        return visitor.visit_AlignBlock(self)

    def __repr__(self):
        return f"AlignBlock({self.align}, inlines={len(self.content)})"


@dataclass
class Table(BlockNode):
    """表格节点"""
    headers: List[str] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)

    def accept(self, visitor: NodeVisitor):
        return visitor.visit_Table(self)

    def __repr__(self):
        return f"Table(cols={len(self.headers)}, rows={len(self.rows)})"


# ============================================================
# 行内节点
# ============================================================

class InlineNode(ASTNode, ABC):
    """所有行内节点的抽象基类"""
    pass


@dataclass
class RawText(InlineNode):
    """原始文本节点"""
    text: str = ""

    def accept(self, visitor: NodeVisitor):
        return visitor.visit_RawText(self)

    def __repr__(self):
        return f"RawText('{self.text[:20]}')"


@dataclass
class Bold(InlineNode):
    """加粗节点: **text**"""
    content: List['InlineNode'] = field(default_factory=list)

    def accept(self, visitor: NodeVisitor):
        return visitor.visit_Bold(self)

    def __repr__(self):
        return f"Bold(inlines={len(self.content)})"


@dataclass
class Italic(InlineNode):
    """斜体节点: *text*"""
    content: List['InlineNode'] = field(default_factory=list)

    def accept(self, visitor: NodeVisitor):
        return visitor.visit_Italic(self)

    def __repr__(self):
        return f"Italic(inlines={len(self.content)})"


@dataclass
class Strikethrough(InlineNode):
    """删除线节点: ~~text~~"""
    content: List['InlineNode'] = field(default_factory=list)

    def accept(self, visitor: NodeVisitor):
        return visitor.visit_Strikethrough(self)

    def __repr__(self):
        return f"Strikethrough(inlines={len(self.content)})"


@dataclass
class InlineCode(InlineNode):
    """行内代码节点: `code`"""
    code: str = ""

    def accept(self, visitor: NodeVisitor):
        return visitor.visit_InlineCode(self)

    def __repr__(self):
        return f"InlineCode('{self.code[:20]}')"


@dataclass
class Link(InlineNode):
    """链接节点: [text](url)"""
    text: str = ""
    url: str = ""

    def accept(self, visitor: NodeVisitor):
        return visitor.visit_Link(self)

    def __repr__(self):
        return f"Link('{self.text[:20]}' -> '{self.url}')"


@dataclass
class Image(InlineNode):
    """图片节点: ![alt](url) 或 ![alt](url 80%)"""
    alt: str = ""
    url: str = ""
    width: str = ""     # 可选宽度，如 "80%"

    def accept(self, visitor: NodeVisitor):
        return visitor.visit_Image(self)

    def __repr__(self):
        w = f', width={self.width}' if self.width else ''
        return f"Image(alt='{self.alt}', url='{self.url}'{w})"


@dataclass
class FunctionCall(InlineNode):
    """自定义函数调用节点: @fn(args)"""
    name: str = ""                              # 函数名
    args: List[str] = field(default_factory=list)       # 位置参数
    kwargs: dict = field(default_factory=dict)           # 关键字参数
    raw_args: str = ""                          # 原始参数字符串

    def accept(self, visitor: NodeVisitor):
        return visitor.visit_FunctionCall(self)

    def __repr__(self):
        return f"FunctionCall({self.name}({self.raw_args}))"


@dataclass
class Color(InlineNode):
    """颜色文本节点: /#hex:text:/"""
    color: str = ""
    text: str = ""

    def accept(self, visitor: NodeVisitor):
        return visitor.visit_Color(self)

    def __repr__(self):
        return f"Color(#{self.color}, '{self.text[:20]}')"


@dataclass
class Superscript(InlineNode):
    """上标节点: ^text^"""
    content: List['InlineNode'] = field(default_factory=list)

    def accept(self, visitor: NodeVisitor):
        return visitor.visit_Superscript(self)

    def __repr__(self):
        return f"Superscript(inlines={len(self.content)})"


@dataclass
class Subscript(InlineNode):
    """下标节点: ~text~"""
    content: List['InlineNode'] = field(default_factory=list)

    def accept(self, visitor: NodeVisitor):
        return visitor.visit_Subscript(self)

    def __repr__(self):
        return f"Subscript(inlines={len(self.content)})"


@dataclass
class RawHtml(InlineNode):
    """HTML 透传节点"""
    html: str = ""

    def accept(self, visitor: NodeVisitor):
        return visitor.visit_RawHtml(self)

    def __repr__(self):
        return f"RawHtml('{self.html[:30]}')"


@dataclass
class FootnoteRef(InlineNode):
    """脚注引用节点: [^label]"""
    label: str = ""
    number: int = 0     # 渲染时分配的数字序号

    def accept(self, visitor: NodeVisitor):
        return visitor.visit_FootnoteRef(self)

    def __repr__(self):
        return f"FootnoteRef(label={self.label}, #{self.number})"


@dataclass
class LineBreak(InlineNode):
    """换行节点"""

    def accept(self, visitor: NodeVisitor):
        return visitor.visit_LineBreak(self)

    def __repr__(self):
        return "LineBreak()"
