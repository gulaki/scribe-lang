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
2. **Names, scopes, labels and types.** This phase only runs when there are no
   syntax errors. It also checks every conversion and assignment. Each
   undeclared variable is reported at its first use only, and an expression
   whose type is unknown because of an earlier error is not checked again.
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
| E0304 | break-outside-loop | `break` or `continue` outside any loop. |
| E0305 | unknown-loop | `break name` or `continue name`, where no loop around it is named `name`. Name the loop to leave with `while cond as name {`; the help lists the names in scope. |
| E0306 | loop-name-in-use | A nested loop reuses the name of a loop around it, so `break name` would be ambiguous. A note points at the outer loop. Loops side by side may share a name. |
| E0401 | number-too-large | A literal does not fit the type it gets: an integer beyond i64, a float that rounds to infinity (above about 1.8e308 for f64, 3.4e38 for f32), or an integer that is not exact in the float type it meets (`f + 16777217` with `f` an f32). |
| E0501 | type-mismatch | An assignment whose value does not convert losslessly to the variable's type, which was fixed by its first assignment. A note points at that assignment. Convert explicitly, e.g. `f64(n)`. |
| E0502 | no-common-type | An operator or comparison mixes types that no type holds exactly, such as i64 and f64. Convert one side with a cast. |
| E0503 | constant-overflow | An integer constant expression, computed exactly, has a result that does not fit its type. |
| E0504 | constant-division-by-zero | `//` or `%` by zero in an integer constant expression, such as `10 // 0`. |
| E0505 | not-a-truth-value | A float used as a condition, as an operand of `not`, `and` or `or`, or in `bool(x)`. Only a bool or an integer can be tested for truth; a float would make NaN true and -0.0 false. Compare it explicitly: `x != 0.0`. |
| E0506 | bool-operator | Arithmetic (`+ - * / // % **`, unary `-` and `+`) or ordering (`< <= > >=`) on a bool. A bool is not a number; convert it with `i64(flag)`, or compare it with `==` and `!=`. |
| E0507 | chained-not-equal | `!=` in a comparison chain. `a != b != c` would not mean that all three differ. Write the pairs you mean with `and`. |
| E0508 | mixed-comparison-chain | A comparison chain that changes direction, such as `a < b > c`, or mixes `==` with `<`. A chain is all `<`/`<=`, all `>`/`>=`, or all `==`. |
| E0509 | cannot-input-type | `input` into a bool. Read an i64 and convert it: `bool(n)`. |
| E0510 | integer-only-operator | `//` or `%` on a float. They work on integers only. Divide floats with `/`, or convert first: `i64(x) // 2`. A float remainder is not available yet. |
| E0511 | float-only-division | `/` on integers. `/` divides floats, so `7 / 2` is 3.5; for whole-number division use `//`, which rounds down, or convert: `f64(a) / f64(b)`. |
| E0512 | negative-exponent | An integer constant raised to a negative power, such as `2 ** -1`. The result would not be an integer; raise a float instead: `2.0 ** -1` is 0.5. |
| E0601 | assignment-count-mismatch | A multiple assignment has a different number of names and values, such as `a, b = 1` or `a = 1, 2`. |
| E0602 | duplicate-assignment-target | A chained or multiple assignment names the same variable twice, such as `a = b = a = 0` or `a, a = 1, 2`. A note points at the first one. |

Codes are grouped by hundreds: `E00xx` driver and internal, `E01xx` syntax,
`E02xx` names and scopes, `E03xx` control flow (loops, labels and `goto`), `E04xx` literals,
`E05xx` types, `E06xx` assignments.

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
| `integer overflow` | An i64 `+`, `-`, `*`, `//`, `**` or negation whose result does not fit, including `-9223372036854775808 // -1`. |
| `division by zero` | An i64 `//` or `%` by zero. Float division by zero is defined: it gives `inf` or `nan`. |
| `negative exponent` | An i64 `**` whose exponent is negative: the result would not be an integer. Raise a float instead: `2.0 ** -1`. |
| `value out of range for i64` | `i64(x)` where `x` is NaN, infinite, or outside the range of i64. |

*Planned* ([runtime-errors.md](design/runtime-errors.md)): runtime errors get
codes (`R0001` integer overflow, ...), propagate through function calls with
a traceback, and end the program with exit status 1 instead of `abort()`.

## Warnings

A warning does not stop compilation: the C is still written. Warnings use
`W` codes, numbered like the errors.

| Code | Name | Meaning |
|---|---|---|
| W0001 | deprecated-goto | `goto` or `label`. Both are deprecated and will be removed in a future version. Leave a loop with `break`, or an outer loop with `break name` / `continue name` (`while ... as name`). |

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
