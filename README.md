# Scribe

Scribe is a small language that compiles to C. It is meant to be easy to read and
write, and hard to get wrong: **a program that compiles never reaches
undefined behaviour in C**. Integer overflow, for example, stops the program
with the Scribe position instead of silently wrapping. The generated C is
plain, readable and builds with `cc -std=c11 -pedantic-errors`.

The compiler is written in Python with [Lark](https://github.com/lark-parser/lark).
It started from Austin Z. Henley's Teeny Tiny compiler tutorial, rebuilt so that
the language can grow without rewriting the front end.

## Quick start

You need Python 3.10 or later and a C compiler (`cc`, `gcc` or `clang`).

```sh
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .

mkdir -p build
scribe examples/types.scribe -o build/types.c
cc -std=c11 build/types.c -o build/types
build/types
```

`scribe` is the same as `python -m scribe_lang.cli`. Programs that read input
take it on stdin: `echo 10 | build/factorial` after building
`examples/factorial.scribe` the same way.

The compiler can also write a build file next to the C file:

```sh
scribe examples/factorial.scribe -o build/factorial.c --build make     # build/Makefile
make -C build
scribe examples/factorial.scribe -o build/factorial.c --build ninja    # build/build.ninja
ninja -C build
```

Other options: `--ast` prints the syntax tree, `--build-output PATH` puts the
build file elsewhere, and `--diagnostics-format json` prints errors as JSON.

## A tour

```scribe
# stdin: 10
i64: n                     # a declaration: n is an i64, starting at 0
input n                    # reads a whole number
a, b = 0, 1                # multiple assignment
while n {                  # an integer condition: true until n is 0
    a, b = b, a + b        # both values use the old a and b
    n = n - 1
}
print a
mean = f64(a) / 2          # i64 and f64 only mix through a cast
print mean
low = high = 0x10          # chained assignment; Python-style literals
if low + high >= 32 {
    print "big"
} else {
    print "small"
}
print 7 // 2               # integer division rounds down
print 2 ** 10              # exact integer power
in_range = 0 < a <= 100    # a comparison chain gives a bool
print in_range and not (a == 0)
```

```output
55
27.50
big
3
1024
true
```

- **[The language reference](docs/language.md)**: every feature, with
  examples that the test suite runs, and what is not available yet.
- **[Examples](examples/README.md)**: complete programs, programs that show
  each error, and proposed syntax for later versions.
- **[Errors](docs/errors.md)**: every error code and runtime error.
- **[Whitepaper](docs/whitepaper.md)** and [design documents](docs/design/):
  the goals, the roadmap and the reasoning behind the rules.

## Errors

Every error in a file is reported in one run, in the style of gcc and clang:

```text
$ python -m scribe_lang.cli examples/errors/many_semantic_errors.scribe
examples/errors/many_semantic_errors.scribe:9:7: error[E0201]: use of undeclared variable 'total'
 9 | print total
   |       ^~~~~
...
7 errors generated.
```

Add `--diagnostics-format json` for machine-readable output. Codes, what they mean, and how to add new ones are in [`docs/errors.md`](docs/errors.md).

## Test

```bash
python -m pytest                     # everything, including compiling the docs' examples
SCRIBE_SANITIZE=1 python -m pytest   # also build every run with UBSan
```

Tests that build C skip themselves when no C compiler is installed.

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
                         │ scopes / types     │
                         └─────────┬──────────┘
                                   │   every phase reports to a shared
                                   │   Diagnostics collector; C is only
                                   │   emitted when there are no errors
                                   │
                         ┌─────────┴──────────┐
                         ▼                    ▼
                  ┌──────────────┐     ┌───────────────┐
                  │ CEmitter     │     │ future backend│
                  │ AST → C      │     │ AST → LLVM... │
                  │ + checks     │     │               │
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

`scribe_lang/grammar/scribe_lang.lark` is the language syntax. You can change the grammar without editing a hand-written lexer or parser.

### 2. AST is the compiler contract

The parser produces a stable AST. Semantic analysis and code generation consume the AST rather than Lark's `Tree` objects. This prevents the parser library from leaking through the compiler.

### 3. Semantic analysis is separate

Name, scope, label and type checks are not mixed into parsing or C generation. The analyzer builds a `Scope` for every block, gives every variable and expression a type (`scribe_lang/types.py` holds the type table and the mixing rule), and the C backend reads that model to decide where each variable is declared and which checked helper each operation needs. This keeps paying off as the language gets functions, classes or overload resolution.

### 4. Backends are replaceable

`CEmitter` is just one backend. A future LLVM, bytecode, interpreter, or another source-language backend can consume the same AST/semantic model.

### 5. Build generation is separate from compilation

Make/Ninja support is not tangled into code generation. More build systems can be added behind `BuildSystem`.

### 6. Errors are data

Phases never print or raise for mistakes in the program. They report `Diagnostic`s (stable code, span, notes, help) to a shared collector and keep going, so one run shows every error. `Compiler.compile()` returns a `CompilationResult` with the diagnostics, and `render.py` formats them as gcc-style text or JSON.

## Extending the language

### Add a new syntax construct

1. Add its syntax to `grammar/scribe_lang.lark`.
2. Add an AST node to `scribe_lang/ast.py`.
3. Add a Transformer method in `parser.py`.
4. Add semantic checks in `semantics.py`, reporting errors with new codes (see [`docs/errors.md`](docs/errors.md#adding-an-error)).
5. Add code generation in the backend(s). If the C can reach undefined behaviour, add a row to [`docs/design/ub-catalogue.md`](docs/design/ub-catalogue.md) and a runtime check.
6. Add tests, and an `examples/errors/` file for each new error code.
7. Document it in [`docs/language.md`](docs/language.md) with `scribe` examples. `tests/test_docs.py` compiles and runs them, so the page cannot fall behind the compiler.

For example, the planned function syntax ([`examples/future/functions.scribe`](examples/future/functions.scribe)) is:

```text
fn fib(i64: n) -> i64 {
    if n <= 1 {
        return n
    }
    return fib(n - 1) + fib(n - 2)
}
```

The grammar would gain `function_decl`, `parameter_list`, `return_stmt`, and `call_expr`; the AST would gain `FunctionDecl`, `Return`, and `Call`; semantic analysis would gain function signatures (scopes already exist); the C backend would translate those nodes.

### Add classes

Classes should not be bolted directly onto `CEmitter`. The type layer already exists (`ScalarType` in `types.py`, `Symbol.type` and `Scope` in `semantics.py`); classes extend it:

```text
ClassDecl
  ├── fields
  └── methods

ClassType      (next to ScalarType)
FunctionSignature
```

The plan for how objects are owned and freed is in [`docs/design/memory-model.md`](docs/design/memory-model.md).

### Change the surface syntax

The compiler does not care whether the grammar eventually becomes BASIC-like, C-like, Python-like, or something completely custom. Change the `.lark` grammar and update the AST transformer to preserve the same semantic concepts.

For a larger syntax redesign, keep the AST stable whenever possible. That lets source syntax evolve independently from the compiler's middle-end and backends.
