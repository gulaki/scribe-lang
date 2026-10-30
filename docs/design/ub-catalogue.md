# Undefined-behaviour catalogue

Rule: a feature may not ship until every row it touches has a mechanism and a test. **Mechanism** is one of: *reject* (compile error), *check* (runtime trap with a located message), *absent* (cannot be expressed in Scribe), *emit* (the emitter writes C that is defined).

| # | C undefined behaviour | Mechanism | Status |
|---|---|---|---|
| 1 | Signed integer overflow | check: `+ - * **` and negation go through helpers that test with ISO C comparisons *before* the operation (CERT INT32-C); constants are folded exactly at compile time; `+%` etc. will wrap via unsigned casts | done for i64 (runtime trap, or E0503 for constants); wrapping operators planned |
| 2 | Integer division/modulo by zero, `INT_MIN / -1`, and `INT_MIN % -1` | check: `//` and `%` go through helpers that test the operands first; `INT64_MIN % -1` returns 0 without evaluating C's `%` | done for i64 (runtime trap, or E0504 for constants); `/` only divides floats. Float division by zero is undefined in ISO C without Annex F (C11 6.5.5p5), so it never happens: `scribe_div_f64`/`scribe_div_f32` return ±inf or nan for a zero divisor themselves, and float `//` and `%` give the IEEE 754 result for a zero divisor, a nan or an infinite dividend before calling `fmod`, whose result C leaves implementation-defined there |
| 3 | Shift by negative or too-large count | check; shifts take a masked/range-checked count | no shifts |
| 4 | Out-of-bounds array/string access | check on every index; elided only when proven | no arrays |
| 5 | Null dereference | absent: no pointers; optional values are `T \| none` and need `match` | n/a |
| 6 | Use of uninitialised variable | emit: every variable is zero-initialised (globals and block locals), and a declaration assigns its value or zero every time it runs | done |
| 7 | Use after free, double free, dangling pointer | absent: no pointers; ownership and second-class borrows (memory-model.md) | n/a |
| 8 | Memory leak (not UB, but forbidden) | emit: scope-exit frees on every path | n/a |
| 9 | Unsequenced modifications / unspecified evaluation order | emit: operands with side effects are hoisted to temporaries; every temporary is written once, then read only after a sequence point (`&&`, `\|\|`, `,`) | partly done. No undefined behaviour: expressions only read variables, and a chain temporary (`(v_a < (t_1 = ...)) && (t_1 < v_c)`) is written once and read after `&&`. Statements, multiple-assignment values, `and`/`or` and chains run left to right. **Gap:** the order of the two operands of one operation is C's, which is unspecified, so when both would fail (`a * a + b * b`, both overflowing), which runtime error is reported can depend on the C compiler. Fixing it needs the IR: functions.md §8 lowers fallible expressions to one operation per statement, roadmap step F1. |
| 10 | Strict-aliasing violations | absent: no casts between pointer types; byte access via `memcpy` | n/a |
| 11 | Out-of-range float-to-int conversion, NaN to int (C11 6.3.1.4) | check in `i64(x)`; constants checked at compile time | done |
| 12 | `printf`-style format string misuse | emit: strings print through `puts`, never as formats; numbers print through `printf` with a fixed format string | done |
| 13 | Invalid/ill-formed program text: trigraphs, bad escapes, non-ASCII source charset | emit: ASCII-only literals with escapes | done |
| 14 | Name clashes with keywords, libc, reserved identifiers (`__x`, `_X`) | emit: prefixed generated names | done |
| 15 | Jump past a declaration / into a scope (`goto`, VLAs) | reject (goto into nested block); locals declared at block top. A named `break`/`continue` only jumps outwards, to a label after a loop or at the end of its body | done |
| 16 | Reading a value whose lifetime ended (returning address of a local) | absent: borrows cannot be returned or stored | n/a |
| 17 | Stack overflow from deep recursion | check: functions in a call-graph cycle count their depth; past the limit (1,000) the call fails with R0005 and a traceback (runtime-errors.md §6) | no functions |
| 18 | Allocation failure (`malloc` returns NULL) | check: single allocation wrapper traps | no heap |
| 19 | Size arithmetic overflow in allocation (`n * sizeof`) | check: overflow-checked multiply in the wrapper | no heap |
| 20 | Modifying a string literal | absent: literals are immutable values; copies are heap strings | no string values |
| 21 | Data races | absent: no threads in v1 | n/a |
| 22 | Calling a function through a wrong-typed pointer / missing prototype | emit: no function pointers in v1; every function has a prototype | n/a |
| 23 | Infinite loops without side effects (C11 forward-progress) | emit: C11 6.8.5p6 lets the compiler assume termination only for a loop whose controlling expression is not a constant expression and whose body has no side effects, such as an empty `while n {}`; such loops will get a volatile touch (proposed) | open; `while true` is safe, because `true` is emitted as the constant `1` and C11 6.8.5p6 does not apply to a constant controlling expression |
| 24 | `scanf` conversion overflow (`%f` out of range is UB) | check: parse with `strtoll`/`strtod`/`strtof` and range-check instead of `scanf` | done: one reader per type; a token that is not a valid value of the type reads as 0 |
| 25 | Float exceptional conditions (C11 6.5p5: overflow to inf, `inf - inf`, ...), the floating-point environment, signalling NaN | assumed: Scribe relies on the C compiler's floats behaving as IEEE 754 binary32/binary64 in the default environment. gcc, clang and MSVC do so unless built with `-ffast-math`, although only a compiler that defines `__STDC_IEC_559__` (Annex F) promises it, and Apple clang does not define it. Where it is cheap, Scribe gives the IEEE answer itself instead of relying on C (division by zero, row 2; `f64 -> f32`, row 26) | accepted, documented |
| 26 | Out-of-range float-to-narrower-float conversion (C11 6.3.1.5), e.g. `(float)1e300` | emit: `f32(x)` rounds as IEEE 754 does (±inf past the f32 range) in a helper, never a plain cast of an out-of-range value; literals are rounded at compile time | done |
| 27 | Integer types narrower than `int` are promoted to `int` before arithmetic, so `u16 * u16` can overflow `int` | emit: small integer types will compute through helpers in a type wide enough for the result | n/a until i8..u32 exist (planned) |
| 28 | Integer literal of the wrong type in a variadic call (`printf("%" PRId64, 5)` passes an `int`) | emit: integer constants are written `INT64_C(n)`; INT64_MIN as `(-INT64_C(9223372036854775807) - 1)` | done |
| 29 | A `bool` holding a value other than 0 or 1 (with `_Bool`, a bad object representation is undefined) | emit: `bool` is a `uint8_t`, never `_Bool`, so every byte value is defined; it starts at 0 and is only ever assigned `0`, `1`, a comparison, `!`, `&&`, `\|\|`, `(n != 0)` or another bool, each of which is 0 or 1 | done: always 0 or 1, by construction |
| 30 | Testing a float for truth: not undefined, but NaN would count as true and `-0.0` as false | reject: a float condition, `not`/`and`/`or` operand, or `bool(x)` is a compile error (E0505) | done |
| 31 | Evaluating a guarded operation anyway (`n == 0 or 10 // n > 1`) | emit: `and`/`or` lower to C `&&`/`\|\|`, which evaluate the right operand only when needed (C11 6.5.13, 6.5.14), so a guarded runtime check never runs | done |
| 32 | A chain evaluating its middle operand twice, or after a comparison failed | emit: a middle operand that is not a name or constant goes into a temporary at its first use (lowering.md) | done |
| 33 | Math library edge cases (`pow` of a negative number to a fractional power, overflow, `0.0 ** -1.0`) | emit: not undefined: C11 7.12.1 makes them domain, pole or range errors with an implementation-defined result, which is the IEEE 754 value (NaN, ±inf) on the compilers of row 25; integer `**` never calls `pow` | done |

## Known gaps

Row 23 (forward progress) is open, and row 9 has a gap: operand order inside
one operation is unspecified in C. Rows marked n/a apply to features that do
not exist yet; each must be done before its feature ships.

## Verification strategy

1. Every generated program in the test suite is compiled with `-std=c11 -pedantic-errors -Wall -Wextra`.
2. A second pass builds with `-fsanitize=undefined -fno-sanitize-recover=all` and runs the same programs, including adversarial inputs (huge numbers, `nan`, empty input): `SCRIBE_SANITIZE=1 pytest`. The runtime-error tests (`run_trapping`) always build with UBSan, so a check that fires too late shows up as a sanitizer report. AddressSanitizer is the next step; it is not in the default runs yet.
3. Each row above gets at least one test that would fail if the mechanism were removed.
4. Runtime templates are fuzzed against a reference implementation (e.g. Python lists) for arrays and strings.
