"""
mslang 命令行工具

用法:
    python -m mslang input.msl              # 输出到 stdout
    python -m mslang input.msl -o out.html  # 输出到文件
    python -m mslang input.msl --tokens     # 输出 Token 流（调试）
    python -m mslang input.msl --ast        # 输出 AST 树（调试）
    echo "# Hello" | python -m mslang -     # 从 stdin 读取
"""

import sys
import argparse
import io
from pathlib import Path


def main():
    if sys.stdout.encoding != 'utf-8' and hasattr(sys.stdout, 'buffer'):
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        prog='mslang',
        description='mslang — 轻量级排版语言 → HTML',
    )
    parser.add_argument(
        'input',
        nargs='?',
        help='输入 .msl 文件路径（使用 "-" 从 stdin 读取）',
    )
    parser.add_argument(
        '-o', '--output',
        help='输出 HTML 文件路径（默认: stdout）',
    )
    parser.add_argument(
        '--tokens',
        action='store_true',
        help='输出 Token 流（调试模式）',
    )
    parser.add_argument(
        '--ast',
        action='store_true',
        help='输出 AST 树（调试模式）',
    )
    parser.add_argument(
        '--no-pretty',
        action='store_true',
        help='不输出格式化的 HTML',
    )
    parser.add_argument(
        '--version', '-V',
        action='version',
        version=f'mslang 0.1.0',
    )

    args = parser.parse_args()

    if args.input is None:
        parser.print_help()
        sys.exit(0)
    elif args.input == '-':
        source = sys.stdin.read()
    else:
        input_path = Path(args.input)
        if not input_path.exists():
            print(f"错误: 文件不存在 — {args.input}", file=sys.stderr)
            sys.exit(1)
        source = input_path.read_text(encoding='utf-8')

    from .lexer import Lexer
    from .parser import Parser
    from .renderer import HTMLRenderer

    if args.tokens:
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        output = lexer.dump_tokens(tokens)
        if args.output:
            Path(args.output).write_text(output, encoding='utf-8')
            print(f"Token 流已写入: {args.output}")
        else:
            print(output)
        return

    if args.ast:
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser_obj = Parser()
        ast = parser_obj.parse(tokens)
        output = parser_obj.dump_ast(ast)
        if args.output:
            Path(args.output).write_text(output, encoding='utf-8')
            print(f"AST 已写入: {args.output}")
        else:
            print(output)
        return

    renderer = HTMLRenderer(pretty=not args.no_pretty)
    html = renderer.render(source)

    if args.output:
        Path(args.output).write_text(html, encoding='utf-8')
        print(f"HTML 已写入: {args.output}")
    else:
        print(html)


if __name__ == '__main__':
    main()
