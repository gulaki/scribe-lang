# Lowering and templates

Status: the naming scheme for variables, labels, temporaries and runtime
helpers, and the shape of the emitted code, are implemented. The IR, runtime
templates and monomorphisation are proposals.

## Stages

```
AST -> typed AST -> typed IR (explicit checks, moves, cleanups)
    -> monomorphised IR -> C AST -> C text with #line
```
Each stage is a pure function over a data structure, printable for tests. Today's compiler goes `AST -> (scopes and types) -> C text`. Checked arithmetic turned out not to need an IR: the emitter picks a small checked helper from each expression's type. The IR becomes the next step with functions and ownership, which need cleanups on every exit edge and moves.

## Naming

All generated names are deterministic and readable.

| Scribe | C |
|---|---|
| variable `x` | `v_x` (Scribe has no shadowing, so never a suffix) — done |
| label `top` | `l_top` — done |
| temporaries | `t_1`, `t_2`, ... — done (multiple assignment, comparison chains), numbered per program for now; per function later |
| runtime helpers | `scribe_add_i64`, `scribe_trap`, `scribe_read_f64`, ... — done |
| function `gcd(i64,i64)` | `f_gcd__i64_i64` |
| overload `describe(f64)` | `f_describe__f64` |
| method `Account.deposit` | `m_Account__deposit` |
| generic `sum_all[i64]` | `f_sum_all__i64` |
| type `Array[i64]` | `Array__i64`, ops `Array__i64__push` |
| cleanup labels | `c_1`, `c_2`, ... |
| result pointer of a function | `r_result` |
| error exit of a function | `fail` |

Prefix letters keep namespaces disjoint (a variable and a function with the same Scribe name never collide). Mangling must be injective; add a test that lowers a corpus and asserts no two Scribe entities share a C name. Emit `#line` so compiler errors and debuggers show Scribe positions.

## Runtime templates

Hand-written, reviewed C stored as template files with a deliberately tiny substitution language:

```c
// templates/array.c.in
typedef struct { @T@ *data; int64_t len, cap; } @Array@;
static inline @T@ @Array@__get(const @Array@ *a, int64_t i) {
    if ((uint64_t)i >= (uint64_t)a->len) scribe_trap_index(i, a->len);
    return a->data[i];
}
```
- Placeholders: `@T@` (element type), `@Array@` (mangled name), `@SIZE@`, nothing else. No logic, no loops.
- The instantiator checks that every placeholder is bound and that no `@` remains.
- A template is instantiated once per element type per program, into a single generated header section, in dependency order.
- The template set is the **trusted base**: reviewed line by line, built under sanitisers, differential-tested against a reference model.

## Monomorphisation

User generics are instantiated in the IR: collect reachable `(function, type-args)` pairs from `main`, clone and substitute, name via the table above, deduplicate. Errors are reported against the generic definition (constraints are checked once, not per instantiation). Recursion in instantiation (`f[T]` calling `f[Array[T]]`) gets a depth limit and an error.

## Division (implemented)

| Scribe | C |
|---|---|
| `x / y` (floats) | `scribe_div_f64(v_x, v_y)` (`scribe_div_f32` for f32): ±inf or nan for a zero divisor, without dividing by zero |
| `x / 2.0` | `(v_x / 2.0)`: a nonzero constant divisor is plain C division |
| `7 / 2` | `(7.0 / 2.0)`: the integer literals are written as floats |
| `a // b` | `scribe_floordiv_i64(v_a, v_b, site)`: traps on 0 and `INT64_MIN // -1`, then adjusts C's truncating `/` |
| `a % b` | `scribe_mod_i64(v_a, v_b, site)`: traps on 0, returns 0 for `b == -1`, then adjusts C's `%` |

## Powers (implemented)

| Scribe | C |
|---|---|
| `n ** 2` (i64) | `scribe_pow_i64(v_n, INT64_C(2), site)`: traps on a negative exponent and on overflow |
| `x ** 0.5` (f64) | `pow(v_x, 0.5)` |
| `y ** 0.5` (f32) | `powf(v_y, 0.5f)` |

## Headers and libraries (implemented)

Every header is included only when the program needs it, `<stdio.h>`
included: `print`, `input` and the runtime-error reporter add it, so a
program with none of them does not include it. Calling a C library function
records the library it lives in (`pow` and `powf`: `m`). The compiler
reports the libraries in `CompilationResult.link_libraries`, the C file
starts with a `/* Link with: -lm */` comment, and the generated Makefile
(`LDLIBS`) and Ninja file (`libs`) link them after the source file, where
static linking needs them.

## Functions and errors (proposed)

The calling convention (every function returns a `scribe_err` status and
writes its result through a pointer), the one-operation-per-statement
lowering of fallible expressions, and the error exit are specified in
[functions.md](functions.md#8-evaluation-order-and-lowering) and
[runtime-errors.md](runtime-errors.md#3-the-c-calling-convention).

## Booleans and conditions (implemented)

| Scribe | C |
|---|---|
| `bool` | `uint8_t` (`<stdint.h>`); every stored value is 0 or 1 |
| `true`, `false` | `1`, `0`: plain constants, so `while true` is a C constant expression |
| `not a` | `(!a)` |
| `a and b`, `a or b` | `(a && b)`, `(a \|\| b)`: C evaluates `b` only if needed, and gives 0 or 1 |
| `a < b` as a value | `(v_a < v_b)` |
| `if a < b` | `if (v_a < v_b)`: no doubled parentheses (clang warns on `if ((a == b))`) |
| `if flag`, `if n` | `if (v_flag)`, `if (v_n != 0)` |
| `a < b <= c` | `((v_a < v_b) && (v_b <= v_c))` |
| `a < b + 1 <= c` | `((v_a < (t_1 = scribe_add_i64(v_b, INT64_C(1), 0))) && (t_1 <= v_c))`: a middle operand that is not a name or constant is evaluated once, at its first use |
| `bool(n)` | `(v_n != 0)` |
| `i64(flag)` | `((int64_t)v_flag)` |
| `print flag` | `puts(v_flag ? "true" : "false");` |

An expression temporary such as `t_1` is declared, set to 0, at the top of
the enclosing C block, next to the hoisted variables, and assigned inside the
expression. That works in a `while` condition and in an `elif` chain, and a
`goto` can never skip the declaration. (Multiple assignment, whose values are
whole statements, puts its temporaries in a C block of its own instead.)

## Shape of emitted code

```c
static int64_t f_gcd__i64_i64(int64_t v_a, int64_t v_b) {
    while (v_b != 0) { ...checked ops via helpers... }
    return v_a;
}
```
Rules: one statement per line; locals declared and zero-initialised at the top of their block; `static` for everything except `main`; checked arithmetic through small `static` helpers, emitted only when used, so the generated code stays readable; the generated code defines no macros (it uses standard ones such as `INT64_C` and `PRId64`). All of these hold today except the ones about functions.

## Build

The CLI writes Makefile/Ninja files next to the C output (paths relative to the build file). Planned: a `--sanitize` option to build with UBSan/ASan, for CI. Today the test suite builds with UBSan itself (`SCRIBE_SANITIZE=1`).
