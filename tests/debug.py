import os
from scribe_lang.parser import Parser
from scribe_lang.compiler import Compiler

from lark import Tree, Token


def print_ast(node, prefix="", is_last=True, is_root=True):
    """Print a Lark AST using Unicode tree characters."""

    if isinstance(node, Tree):
        label = str(node.data)
        children = node.children
    elif isinstance(node, Token):
        label = f"{node.type}: {node.value!r}"
        children = []
    else:
        label = repr(node)
        children = []

    if is_root:
        print(label)
    else:
        connector = "└── " if is_last else "├── "
        print(prefix + connector + label)

    if isinstance(node, Tree):
        child_prefix = prefix if is_root else (
            prefix + ("    " if is_last else "│   ")
        )

        for i, child in enumerate(children):
            print_ast(
                child,
                prefix=child_prefix,
                is_last=(i == len(children) - 1),
                is_root=False,
            )

_path = os.path.dirname(__file__)

examples = ['factorial', 'fibonacci', 'loop_goto', 'sum_avg']

ch = examples[1]

with open(os.path.join(_path, '..', 'examples', '.'.join([ch, 'scribe']))) as f:
    source = f.read()
print(source)

# Pretty print the AST
parser = Parser()
tree = parser._parser.parse(source)
print_ast(tree)

compiler = Compiler()
result = compiler.compile(source=source)
print(result)
