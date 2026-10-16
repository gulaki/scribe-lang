# Undefined-behaviour catalogue

Rule: a feature may not ship until every row it touches has a mechanism and a test. **Mechanism** is one of: *reject* (compile error), *check* (runtime trap with a located message), *absent* (cannot be expressed in Scribe), *emit* (the emitter writes C that is defined).

| # | C undefined behaviour | Mechanism | Status in v0.1 |
|---|---|---|---|
| 1 | Signed integer overflow | check: `+ - *` lower to `__builtin_*_overflow` helpers; `+%` etc. wrap via unsigned casts | n/a (no ints); float literals already rejected if they overflow |
| 2 | Integer division/modulo by zero, `INT_MIN / -1` | check | float `/ 0` gives IEEE `inf`, defined |
| 3 | Shift by negative or too-large count | check; shifts take a masked/range-checked count | no shifts |
| 4 | Out-of-bounds array/string access | check on every index; elided only when proven | no arrays |
| 5 | Null dereference | absent: no pointers; optional values are `T \| none` and need `match` | n/a |
| 6 | Use of uninitialised variable | emit: every variable is zero-initialised (globals and block locals) | done |
| 7 | Use after free, double free, dangling pointer | absent: no pointers; ownership and second-class borrows (memory-model.md) | n/a |
| 8 | Memory leak (not UB, but forbidden) | emit: scope-exit frees on every path | n/a |
| 9 | Unsequenced modifications / unspecified evaluation order | emit: operands with side effects are hoisted to temporaries; Scribe defines left-to-right | expressions are pure today |
| 10 | Strict-aliasing violations | absent: no casts between pointer types; byte access via `memcpy` | n/a |
| 11 | Out-of-range float-to-int conversion, NaN to int | check in `int(x)` | no conversion yet |
| 12 | `printf`-style format string misuse | emit: strings print through `puts`/`fwrite`, never as formats | done |
| 13 | Invalid/ill-formed program text: trigraphs, bad escapes, non-ASCII source charset | emit: ASCII-only literals with escapes | done |
| 14 | Name clashes with keywords, libc, reserved identifiers (`__x`, `_X`) | emit: prefixed generated names | done |
| 15 | Jump past a declaration / into a scope (`goto`, VLAs) | reject (goto into nested block); locals declared at block top | done |
| 16 | Reading a value whose lifetime ended (returning address of a local) | absent: borrows cannot be returned or stored | n/a |
| 17 | Stack overflow from deep recursion | check: depth counter, trap at limit (proposed) | no functions |
| 18 | Allocation failure (`malloc` returns NULL) | check: single allocation wrapper traps | no heap |
| 19 | Size arithmetic overflow in allocation (`n * sizeof`) | check: overflow-checked multiply in the wrapper | no heap |
| 20 | Modifying a string literal | absent: literals are immutable values; copies are heap strings | no string values |
| 21 | Data races | absent: no threads in v1 | n/a |
| 22 | Calling a function through a wrong-typed pointer / missing prototype | emit: no function pointers in v1; every function has a prototype | n/a |
| 23 | Infinite loops without side effects (C11 forward-progress) | emit: loops only compile as-is under C11 where the controlling expression is non-constant; trivially infinite loops get a volatile touch (proposed) | open |
| 24 | `scanf` conversion overflow (`%f` out of range is UB) | check: parse with `strtof` and range-check instead of `scanf("%f")` | **gap: v0.1 still uses scanf** |
| 25 | Floating-point environment / signalling NaN | emit: default environment; NaN compares as in IEEE (defined) | accepted |

## Known gaps in v0.1

- Row 24: `input` calls `scanf("%f", ...)`. The C standard makes the result of an out-of-range conversion undefined. Fix: read a token and use `strtof` with `errno` and `isfinite` checks.
- `-Wparentheses-equality`: the emitter wraps comparisons in double parentheses (`if ((v_r == 0.0f))`), which clang warns about. Harmless, but it is noise a user will see in strict builds; emit single parentheses.

## Verification strategy

1. Every generated program in the test suite is compiled with `-std=c11 -pedantic-errors -Wall -Wextra`.
2. A second pass builds with `-fsanitize=undefined,address -fno-sanitize-recover` and runs the same programs, including adversarial inputs (huge numbers, `nan`, empty input).
3. Each row above gets at least one test that would fail if the mechanism were removed.
4. Runtime templates are fuzzed against a reference implementation (e.g. Python lists) for arrays and strings.
