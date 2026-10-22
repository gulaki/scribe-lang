# Changelog

Language versions follow the roadmap in [`docs/whitepaper.md`](docs/whitepaper.md#4-roadmap).
The language as it is now is described in [`docs/language.md`](docs/language.md).

## Unreleased: 0.2 (in progress)

### Added

- Scalar types `i64`, `f64` and `f32`. A variable gets the type of its first
  assignment, and mixing types never loses a value silently: `i64 + f64`
  needs a cast such as `f64(n)`.
- Number literals in Python syntax: `1_000`, `0x1f`, `0o17`, `0b101`, `1e-3`,
  and `2.5f` for f32. Integer constant expressions are folded exactly.
- Checked integer arithmetic. Overflow, integer division by zero and an
  out-of-range `i64(x)` stop the program with a runtime error and the Scribe
  position, instead of undefined behaviour in C.
- Explicit declarations: `i64: a, b = 5`.
- Chained assignment `a = b = 0` and multiple assignment `a, b = b, a`.
- `bool`, with `true` and `false`, `not`, `and`, `or`. `and` and `or` are
  short-circuit, so `n == 0 or 10 // n > 1` never divides by zero.
- Conditions are any bool or integer expression: `while n {`.
- Comparisons give a `bool`, and chain in one direction: `a < b <= c`.
  Unlike Python, `!=` and mixed directions (`a < b > c`) cannot be chained.
- `print` of a bool shows `true` or `false`; `input` reads the variable's type.
- `//` integer division and `%` remainder. Both round down, as in Python:
  `-7 // 2` is -4 and `-7 % 3` is 2.
- Errors E0109, E0203, E0501–E0511 and E0601–E0602; see
  [`docs/errors.md`](docs/errors.md).
- [`docs/language.md`](docs/language.md), a language reference whose examples
  are compiled and run by the test suite.

### Changed (breaking)

- `a = 5` is now an integer. Integers print without decimals (`120`, not
  `120.00`).
- `/` divides floats: `7 / 2` is 3.5, and `/` on an integer variable is an
  error. Use `//` for integer division.
- The type names (`i8` ... `u64`, `f16` ... `f128`, `bool`, `char`, `byte`,
  `str`) and `true`, `false`, `and`, `or`, `not` are reserved words.

## 0.1

- Float-only language: `print`, `input`, assignment, `if`/`elif`/`else`,
  `while`, blocks with scopes, `label` and `goto`, compiled to C.
- Errors reported with stable codes, all in one run, as text or JSON.
