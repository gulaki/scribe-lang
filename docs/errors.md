# Compiler errors

The compiler reports every error it can find in one run, in source order:

```text
examples/errors/undeclared_variable.scribe:4:11: error[E0201]: use of undeclared variable 'y'
 4 | print x + y
   |           ^
1 error generated.
```

Each error has a stable **code** (`E0201`) and **name** (`undeclared-variable`).
Codes are never renumbered or reused, so tests, scripts and editors can rely on
them; the wording of a message may still improve. `--diagnostics-format json`
prints the same information as JSON on stderr.

## How errors are found

1. **Syntax.** After a syntax error the parser skips to the next statement and
   carries on, so each broken statement is reported once. A statement ends at
   the next newline or `;`. If it opens a `{`, it ends at the matching `}`, so
   an error in `if x > {` skips the whole `if` and its body. An error at the
   very end of the file (such as a missing `}`) ends the search.
2. **Names, scopes and labels.** This phase only runs when there are no syntax
   errors. Each undeclared variable is reported at its first use only.
3. **C generation.** This phase only runs when there are no errors at all; no
   C file is written otherwise.

Exit codes: `0` success, `1` errors in the program, `2` bad command line,
`3` internal compiler error (a bug: please report it with the traceback).

## Codes

Every code has at least one example in [`examples/errors/`](../examples/errors/).

| Code | Name | Meaning |
|---|---|---|
| E0001 | internal-error | The compiler itself failed. Not your program's fault. |
| E0002 | cannot-read-source | The source file is missing, unreadable or not UTF-8. |
| E0101 | unexpected-token | Something appeared where it cannot go. The message says what was expected instead. |
| E0102 | unexpected-character | A character that is not part of the language, such as `@`. |
| E0103 | unexpected-end-of-file | The file ends in the middle of a statement. |
| E0104 | unclosed-block | A `{` has no matching `}`. Points at the `{`; a note shows where the file ends. |
| E0105 | misplaced-else | `else` or `elif` starts a new line. It must follow the closing `}` on the same line: `} else {`. |
| E0106 | unterminated-string | A string has no closing `"` on its line. |
| E0107 | unmatched-closing-brace | A `}` with no `{` to close. |
| E0108 | invalid-escape | A string escape other than `\"`, `\\`, `\n`, `\r` and `\t`. |
| E0109 | leading-zero | A decimal number that starts with `0`, such as `017`. In C that would be octal 15. Write `17`, or `0o17` for octal. |
| E0201 | undeclared-variable | A variable is read before anything was assigned to it in a visible scope. A note shows where a variable from a block that already ended was declared. |
| E0202 | reserved-name | A keyword such as `print` or `else` used as a variable or label name. |
| E0203 | already-declared | A declaration such as `i64: x` names a variable that is already visible, in this block or an enclosing one. Scribe has no shadowing. A note points at the first declaration. |
| E0301 | undeclared-label | `goto` names a label that does not exist. |
| E0302 | duplicate-label | Two labels have the same name. A note points at the first one, which stays in effect. |
| E0303 | goto-into-block | `goto` may only jump within its own block or out to an enclosing one. A note points at the label. |
| E0401 | number-too-large | A literal does not fit the type it gets: an integer beyond i64, a float that rounds to infinity (above about 1.8e308 for f64, 3.4e38 for f32), or an integer that is not exact in the float type it meets (`f + 16777217` with `f` an f32). |
| E0501 | type-mismatch | An assignment whose value does not convert losslessly to the variable's type, which was fixed by its first assignment. A note points at that assignment. Convert explicitly, e.g. `f64(n)`. |
| E0502 | no-common-type | An operator or comparison mixes types that no type holds exactly, such as i64 and f64. Convert one side with a cast. |
| E0503 | constant-overflow | An integer constant expression, computed exactly, has a result that does not fit its type. |
| E0504 | constant-division-by-zero | Division by zero in an integer constant expression, such as `10 / 0`. |

Codes are grouped by hundreds: `E00xx` driver and internal, `E01xx` syntax,
`E02xx` names and scopes, `E03xx` labels and `goto`, `E04xx` literals,
`E05xx` types.

## Runtime errors

Some mistakes can only be detected while the program runs. The generated C
checks for them before doing the operation, because in C each one is
undefined behaviour. A failed check prints the Scribe position and stops the
program (`abort()`, so the exit status is nonzero):

```text
prog.scribe:4:11: runtime error: integer overflow
```

| Message | Cause |
|---|---|
| `integer overflow` | An i64 `+`, `-`, `*`, `/` or negation whose result does not fit, including `-9223372036854775808 / -1`. |
| `division by zero` | An i64 division by zero. Float division by zero is defined: it gives `inf` or `nan`. |
| `value out of range for i64` | `i64(x)` where `x` is NaN, infinite, or outside the range of i64. | Warnings,
when there are some, will use `W` codes.

## Adding an error

1. Register a code in `scribe_lang/diagnostics.py` (next free number in its
   group) with a message template.
2. Report it from the phase that detects it:
   `diagnostics.error(codes.MY_ERROR, node.location, name=..., notes=..., help=...)`.
   Keep analysing afterwards, and avoid follow-on errors that only repeat the
   first one.
3. For a syntax mistake that deserves a specific message, add a hint function
   to `_HINTS` in `scribe_lang/parser.py`.
4. Add an `examples/errors/` file with `# expect: <code> at <line>:<column>`
   lines, and a row to the table above. Tests fail until both exist.
