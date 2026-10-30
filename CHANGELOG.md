# Changelog

All notable changes to Scribe: the language, the `scribe` command and the C
it generates. The language as it is now is described in
[`docs/language.md`](docs/language.md). The current version is in
[`VERSION.txt`](VERSION.txt).

## Versioning

Versions follow [Semantic Versioning](https://semver.org). Before 1.0 the
first number stays 0, and:

- a **breaking** change (a valid program changes meaning or stops compiling,
  or the package or command is renamed) increases the **second** number;
- a new feature or a fix that breaks nothing increases the **third** number.

Each pull request merged into `main` that changes the compiler is one
release; one that only changes documentation keeps the version. To release,
move the "Unreleased" entries under a new `## X.Y.Z - date` heading and write
the same version in `VERSION.txt` (a test checks that they agree). The
versions up to 0.5.1 were worked out afterwards from the commits and pull
requests; only 0.0.1 and 0.1.0 were named at the time. The roadmap's stages (M1, M2, ... in
[`docs/whitepaper.md`](docs/whitepaper.md#4-roadmap)) are plans, not version
numbers.

## 0.6.2 - 2026-10-30

Pull request #12.

### Added

- `//` and `%` on floats (f64 and f32), exact on the values the floats
  hold: `x // y` is the floor of the exact quotient and `x % y` the exact
  remainder, each rounded once. `1 // 0.1` is 9.0, because the float 0.1 is
  a little more than one tenth. A zero divisor gives `inf` or `nan`, as for
  `/`. Programs that use them link with `-lm`.

### Removed

- Error E0510 (`//` or `%` on a float). The code is retired and will not be
  reused; [`docs/errors.md`](docs/errors.md#retired-codes) lists retired
  codes.

## 0.6.1 - 2026-10-30

Pull request #11.

### Added

- `--target wasm`: build a program as WebAssembly with Emscripten.
  `--shell web` (the default) writes a folder with a page that runs the
  unchanged program in a browser terminal (xterm.js with xterm-pty, input
  through Asyncify), with runtime errors in red, a remembered
  System/Light/Dark theme and a Rerun button; serve it with
  `python -m http.server`. `--shell node` builds for `node`.
- `--web-assets vendored` (the default) copies the terminal's libraries into
  the folder; `--web-assets cdn` links them from jsDelivr with SRI hashes.
- `--build make` and `--build ninja` work for both targets; build files take
  link flags and extra outputs.

### Fixed

- Generated Makefiles now use their compiler: make predefines `CC`, so
  `CC ?= cc` never took effect (native builds only worked because the
  default is also `cc`).

## 0.6.0 - 2026-10-25

Pull request #9.

### Added

- `break` and `continue`. `while cond as name {` names a loop, so `break
  name` and `continue name` reach it from loops nested inside. Errors E0304
  to E0306.
- Warnings, starting with W0001; [`docs/errors.md`](docs/errors.md) lists
  them.
- The `f2c.scribe` example (Fahrenheit to Celsius, types inferred through an
  expression) and `loop_break.scribe`, which replaces `loop_goto.scribe`.

### Changed (breaking)

- `break`, `continue` and `as` are reserved words.

### Deprecated

- `goto` and `label` give warning W0001 and will be removed in a future
  version. `primes.scribe` and `newton_sqrt.scribe` now use `continue` and
  `break`.

## 0.5.2 - 2026-10-23

Pull request #8.

### Fixed

- Dividing a float by zero no longer depends on the C compiler. ISO C leaves
  it undefined unless the compiler implements Annex F, so `/` on floats goes
  through a helper that returns `inf`, `-inf` or `nan` itself.

### Changed

- The version lives in `VERSION.txt`, which `pyproject.toml` reads; `scribe
  --version` prints it.
- The roadmap's stages are named M1 to M9 instead of 0.1 to 0.9, so they
  can't be mistaken for versions.
- Draft specifications for functions and runtime errors with tracebacks
  ([`docs/design/functions.md`](docs/design/functions.md),
  [`docs/design/runtime-errors.md`](docs/design/runtime-errors.md)).

## 0.5.1 - 2026-10-23

Pull request #7.

### Added

- `**`, with Python's precedence: it binds tighter than a sign on its left
  and groups from the right (`-2 ** 2` is -4). Integer powers are exact and
  checked; float powers call `pow`/`powf`.
- Error E0512 (negative constant exponent) and the runtime error "negative
  exponent".
- Headers are included, and libraries linked, only when a program uses them,
  `<stdio.h>` included. A program with a float `**` needs `-lm`: its C file
  starts with `/* Link with: -lm */`, and `--build make`/`--build ninja` add
  it.

## 0.5.0 - 2026-10-22

Pull request #6.

### Changed (breaking)

- `/` divides floats: `7 / 2` is 3.5, and `/` on an integer variable is an
  error (E0511). Integer division is `//`.

### Added

- `//` integer division and `%` remainder. Both round down, as in Python:
  `-7 // 2` is -4 and `-7 % 3` is 2. On floats they are an error (E0510).

## 0.4.0 - 2026-10-22

Pull request #5.

### Added

- `bool`, with `true` and `false`, `not`, `and`, `or`. `and` and `or` are
  short-circuit, so `n == 0 or 10 // n > 1` never divides by zero.
- Conditions are any bool or integer expression: `while n {`.
- Comparisons give a `bool` and chain in one direction: `a < b <= c`. Unlike
  Python, `!=` and mixed directions (`a < b > c`) cannot be chained.
- `print` of a bool shows `true` or `false`.
- Errors E0505 to E0509.

### Changed (breaking)

- `true`, `false`, `and`, `or` and `not` are reserved words.

## 0.3.0 - 2026-10-22

Pull request #4.

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
- `input` reads a value of the variable's type.
- Errors E0109, E0203, E0501 to E0504, E0601 and E0602; see
  [`docs/errors.md`](docs/errors.md).
- [`docs/language.md`](docs/language.md), a language reference whose examples
  are compiled and run by the test suite.

### Changed (breaking)

- `a = 5` is an integer, no longer a float. Integers print without decimals
  (`120`, not `120.00`).
- A decimal number cannot start with `0` (`017`); write `0o17` for octal.
- The type names (`i8` ... `u64`, `f16` ... `f128`, `bool`, `char`, `byte`,
  `str`) are reserved words.

## 0.2.3 - 2026-10-21

Pull request #3.

### Added

- Every error in a file is reported in one run, with a stable code (E0001 to
  E0401), the source line and, where useful, notes and help.
- Errors print in gcc and clang style, or as JSON with
  `--diagnostics-format json`.
- The parser recovers after a syntax error and reports one error per broken
  statement, with specific messages for common mistakes.
- Exit codes: 0 success, 1 errors in the program, 2 bad command line, 3
  internal error.

## 0.2.2 - 2026-10-21

Pull request #2.

### Fixed

- Number literals are emitted as C float literals, and ones too large are
  rejected.
- Strings print through `puts` with ASCII-only escapes, so `%` in a string is
  never read as a format.
- Variables and labels get `v_` and `l_` prefixes, so no Scribe name clashes
  with C.
- `input` reads with `strtof`: an out-of-range or malformed token reads as 0
  instead of reaching `scanf`'s undefined behaviour.
- Build files are written next to the C file, with paths relative to the
  build file.
- Comparisons no longer get doubled parentheses (a clang warning).

### Added

- The whitepaper, the design documents (UB catalogue, type system, memory
  model, lowering), and the `examples/errors` and `examples/future` folders.

## 0.2.1 - 2026-10-14

### Fixed

- Leftover Teeny Tiny names in the command's messages, the README and the
  Makefile.

## 0.2.0 - 2026-10-12

Pull request #1.

### Changed (breaking)

- Renamed to Scribe: the package is `scribe-lang` (was `teenytiny-lark`),
  the module `scribe_lang`, the command `scribe` (was `ttc`), and source files
  end in `.scribe`.

## 0.1.0 - 2026-10-09

### Changed (breaking)

- Keywords are lower case.
- Assignment is `x = e`, without `LET`.
- Blocks are `{ ... }` instead of `THEN ... ENDIF` and `REPEAT ... ENDWHILE`.
  Each block is a scope.
- Statements are separated by newlines or `;`.

### Added

- `if`/`elif`/`else`.
- Tests and more examples.

## 0.0.1 - 2026-10-05

- The Teeny Tiny compiler rewritten in Python with Lark. It has float-only
  variables, `PRINT`, `INPUT`, `LET`, `IF ... THEN ... ENDIF`,
  `WHILE ... REPEAT ... ENDWHILE`, `LABEL` and `GOTO`, compiles to C, and
  writes Make or Ninja build files.
