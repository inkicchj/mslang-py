"""
mslang — A Lightweight Markup Language

类似于 Markdown 的轻量级排版语言，完整实现了：
  词法解析器 (Lexer)  →  语法解析器 (Parser)  →  渲染引擎 (Renderer)

使用:

    from mslang import HTMLRenderer

    renderer = HTMLRenderer()
    renderer.add_function('greet', greet)
    html = renderer.render('Hello @greet(World)')
"""

__version__ = '0.1.0'
__author__ = 'mslang'

from .renderer import HTMLRenderer

__all__ = ['HTMLRenderer']
