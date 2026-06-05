"""
mslang Token 定义

定义词法解析阶段所有 Token 类型及其数据结构。
每个 Token 带有行号、列号信息，便于错误定位。
"""

from enum import Enum, auto
from dataclasses import dataclass
from typing import Optional


class TokenType(Enum):
    """mslang 词法单元类型枚举"""

    # === 块级元素 ===
    HEADING         = auto()   # # ~ ######
    HORIZONTAL_RULE = auto()   # --- / *** / ___
    BLOCKQUOTE      = auto()   # >
    CODE_BLOCK      = auto()   # ``` ... ```
    UNORDERED_LIST  = auto()   # - / * / +
    ORDERED_LIST    = auto()   # 1. / 2. / ...

    # === 行内元素 ===
    BOLD            = auto()   # **text** 或 __text__
    ITALIC          = auto()   # *text* 或 _text_
    STRIKETHROUGH   = auto()   # ~~text~~
    INLINE_CODE     = auto()   # `code`
    LINK            = auto()   # [text](url)
    IMAGE           = auto()   # ![alt](url)
    FUNCTION_CALL   = auto()   # @name(args...)
    COLOR           = auto()   # /#hex:text:/
    SUPERSCRIPT     = auto()   # ^text^
    SUBSCRIPT       = auto()   # ~text~
    TABLE_ROW       = auto()   # | cell | cell |
    TABLE_SEP       = auto()   # |---|---|
    FOOTNOTE_REF    = auto()   # [^label]
    FOOTNOTE_DEF    = auto()   # [^label]: content
    ALIGN_RIGHT     = auto()   # >> text
    ALIGN_CENTER    = auto()   # -><- text

    # === 文本与空白 ===
    RAW_TEXT        = auto()   # 原始文本
    LINE_BREAK      = auto()   # 换行（段落内）
    BLANK_LINE      = auto()   # 空行（段落分隔）

    # === 特殊 ===
    EOF             = auto()   # 文件结束


@dataclass
class Position:
    """源码位置信息"""
    line: int       # 行号（从 1 开始）
    col: int        # 列号（从 1 开始）
    index: int      # 字符索引（从 0 开始）

    def __repr__(self):
        return f"L{self.line}:C{self.col}"


@dataclass
class Token:
    """mslang 词法单元"""
    type: TokenType
    position: Position
    value: str = ""             # 原始匹配文本
    metadata: Optional[dict] = None  # 附加元数据（如 heading_level, list_marker 等）

    def __repr__(self):
        meta = f" | meta={self.metadata}" if self.metadata else ""
        return f"Token({self.type.name}, '{self.value[:20]}', {self.position}{meta})"


# 字符与符号常量（用于词法分析）
AT              = '@'
SLASH           = '/'
BACKTICK        = '`'
STAR            = '*'
UNDERSCORE      = '_'
TILDE           = '~'
HASH            = '#'
GT              = '>'
HYPHEN          = '-'
PLUS            = '+'
DOT             = '.'
BANG            = '!'
LBRACKET        = '['
RBRACKET        = ']'
LPAREN          = '('
RPAREN          = ')'
PIPE            = '|'
NEWLINE         = '\n'
