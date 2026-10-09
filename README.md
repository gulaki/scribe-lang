# Teeny Tiny Compiler — Python + Lark

A modern rewrite of Austin Z. Henley's three-part Teeny Tiny compiler tutorial.

The original compiler is deliberately educational: it has a hand-written lexer, a hand-written recursive-descent parser, and an emitter that produces C. This version keeps the language and C target, but changes the architecture so that language evolution does not require rewriting the compiler front-end.

## Architecture

```text
                         ┌────────────────────┐
 source ────────────────►│ Lark LALR parser    │
                         │ contextual lexer    │
                         └─────────┬──────────┘
                                   │ parse tree
                                   ▼
                         ┌────────────────────┐
                         │ ASTBuilder         │
                         │ concrete → AST     │
                         └─────────┬──────────┘
                                   │
                                   ▼
                         ┌────────────────────┐
                         │ SemanticAnalyzer   │
                         │ scopes / labels    │
                         └─────────┬──────────┘
                                   │
                         ┌─────────┴──────────┐
                         ▼                    ▼
                  ┌──────────────┐     ┌───────────────┐
                  │ CEmitter     │     │ future backend│
                  │ AST → C      │     │ AST → LLVM... │
                  └──────┬───────┘     └───────────────┘
                         │
                         ▼
                       C file
                         │
               ┌─────────┴──────────┐
               ▼                    ▼
             Make                 Ninja
```

## Why this structure?

### 1. Grammar is data

`teenytiny/grammar/teenytiny.lark` is the language syntax. You can change the grammar without editing a hand-written lexer or parser.

### 2. AST is the compiler contract

The parser produces a stable AST. Semantic analysis and code generation consume the AST rather than Lark's `Tree` objects. This prevents the parser library from leaking through the compiler.

### 3. Semantic analysis is separate

Variable, scope and label checks are not mixed into parsing or C generation. The analyzer builds a `Scope` for every block and the C backend reads those scopes to decide where each variable is declared. This keeps paying off as the language gets functions, classes, types, or overload resolution.

### 4. Backends are replaceable

`CEmitter` is just one backend. A future LLVM, bytecode, interpreter, or another source-language backend can consume the same AST/semantic model.

### 5. Build generation is separate from compilation

Make/Ninja support is not tangled into code generation. More build systems can be added behind `BuildSystem`.

## Install

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -e .
```

## Compile

```bash
python -m teenytiny.cli examples/fibonacci.teeny -o build/fibonacci.c
```

Generate Make:

```bash
python -m teenytiny.cli examples/fibonacci.teeny \
  -o build/fibonacci.c \
  --build make \
  --build-output build/Makefile
```

Generate Ninja:

```bash
python -m teenytiny.cli examples/fibonacci.teeny \
  -o build/fibonacci.c \
  --build ninja \
  --build-output build/build.ninja
```

## Language reference

```text
# Comments run to the end of the line.
print "text"            # string
print x * 2 + 1         # expression, printed with two decimals
input n                 # read a number
x = (n + 1) * 2         # assignment; all values are C floats

if x > 10 {             # comparison operators: == != > >= < <=
    print "big"
} elif x > 5 {
    print "medium"
} else {
    print "small"
}

while x > 0 {
    x = x - 1
}

{                       # a bare block is just a scope
    scratch = 1
}

label top               # labels and goto still exist
goto top
```

**Blocks and separators.** Statements are separated by newlines or `;`, so a block may sit on one line: `if x > 0 { print x; x = x - 1 }`. The opening `{` must be on the same line as its `if`/`elif`/`else`/`while`, and `}` must be on the same line as the `elif`/`else` that follows it (`} else {`).

**Scope rules.**

- `{ ... }` opens a scope; the program itself is the outermost scope.
- `x = e` and `input x` assign to `x` if a variable named `x` is already visible. Otherwise they declare `x` in the innermost scope. There is no shadowing.
- The right-hand side is checked first, so `x = x + 1` is an error unless `x` already exists.
- A variable is gone after the block that declared it ends, and the blocks of an `if`/`elif`/`else` chain are separate scopes.
- Conditions of `if`, `elif` and `while` are evaluated in the enclosing scope.
- Labels share one program-wide namespace. `goto` may jump within its own block or out to an enclosing block, never into a nested block.
- `print`, `input`, `if`, `elif`, `else`, `while`, `label` and `goto` are reserved words.

**What the C looks like.** Program-level variables become zero-initialised globals. A variable first assigned inside a block is declared as `float x = 0;` at the top of the matching C block, so every variable starts at 0 and a `goto` inside a block can never jump over a declaration.

## Test

```bash
python -m pytest
```

## Extending the language

### Add a new syntax construct

1. Add its syntax to `grammar/teenytiny.lark`.
2. Add an AST node to `teenytiny/ast.py`.
3. Add a Transformer method in `parser.py`.
4. Add semantic checks in `semantics.py`.
5. Add code generation in the backend(s).
6. Add tests.

For example, a future function syntax could be:

```text
function fib(n) {
    if n <= 1 {
        return n
    }
    return fib(n - 1) + fib(n - 2)
}
```

The grammar would gain `function_decl`, `parameter_list`, `return_stmt`, and `call_expr`; the AST would gain `FunctionDecl`, `Return`, and `Call`; semantic analysis would gain function signatures (scopes already exist); the C backend would translate those nodes.

### Add classes

Classes should not be bolted directly onto `CEmitter`. Add a type/symbol layer first:

```text
ClassDecl
  ├── fields
  └── methods

TypeInfo
Scope
Symbol
FunctionSignature
```

Then choose how the target represents objects: C structs + functions, C++, LLVM IR, etc.

### Change the surface syntax

The compiler does not care whether the grammar eventually becomes BASIC-like, C-like, Python-like, or something completely custom. Change the `.lark` grammar and update the AST transformer to preserve the same semantic concepts.

For a larger syntax redesign, keep the AST stable whenever possible. That lets source syntax evolve independently from the compiler's middle-end and backends.
