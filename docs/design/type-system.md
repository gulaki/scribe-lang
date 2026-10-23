# Type system

Status: **scalars i64, f64, f32 and bool are implemented**, with literals,
inference, declarations, chained and multiple assignment, casts, checked
arithmetic, `/` `//` `%` `**`, logical operators and comparison chains. To *use* them, read the [language reference](../language.md).
This page records the rules, the reasons for them, and what comes next; items
marked *planned* do not exist yet.

The goal that decides every rule here: arithmetic is never silently wrong.
No implicit conversion loses information, and integer overflow is a runtime
error, never C undefined behaviour or a quiet wrap.

## Status and next steps

The type system is built in numbered tasks, each starting from failing tests.

| # | Task | Status |
|---|---|---|
| 1 | `i64`, `f64`, `f32`; Python-style literals; inference; checked i64 arithmetic; casts | done |
| 2 | `bool`, `true`/`false`, `and`/`or`/`not`; conditions as expressions (`while n {`); comparison chains | done |
| 3 | `i8` ... `i32`, `u8` ... `u64` (`char`, `byte` = `u8`), the full promotion table | next |
| 4 | Explicit declarations `i64: a, b = 5` | done |
| 5 | Chained `a = b = 0` and multiple `a, b = b, a` assignment | done |
| 6 | `**`: checked integer powers, `pow`/`powf` for floats; headers and `-lm` only when used | done |
| 7 | `f16`, `f128`, per target | planned |
| 8 | Range analysis that removes provably safe checks | planned |
| 9 | `/` divides floats; integer `//` and `%`, rounding down | done |

Also planned, not yet numbered: wrapping operators (`+%`, `wrap_u8(x)`);
`//` and `%` for floats, now that programs can link the C maths library; and
`floor(x)` and the other maths functions, with function calls and `use math`.
Functions themselves are drafted in [functions.md](functions.md) and
[runtime-errors.md](runtime-errors.md).

## Scalars

| Type | C lowering | Status |
|---|---|---|
| `i64` | `int64_t` | implemented; checked arithmetic |
| `f64` | `double` | implemented; IEEE 754 |
| `f32` | `float` | implemented; IEEE 754 |
| `i8` `i16` `i32`, `u8` `u16` `u32` `u64` | `int8_t` ... `uint64_t` | planned; `char` and `byte` are `u8` |
| `bool` | `uint8_t`, always 0 or 1 | implemented; see [Booleans](#booleans) |
| `f16`, `f128` | `_Float16`, `_Float128` | planned, per target: not in C11, and Apple arm64 has no binary128 |
| `str` | an array, once arrays exist | planned |

Every type name is a reserved word already, so programs written now keep
working when the type arrives.

## Literals

Number literals use Python 3 syntax: `1_000`, `0x1f`, `0o17`, `0b101`, `2.5`,
`.5`, `5.`, `1e-3`. A decimal integer may not start with `0` (`017` is an
error, E0109) because in C it would be octal. A trailing `f` on a float
literal makes it f32: `2.5f`, `1e3f`.

Literals are **untyped**: they take the type their context needs.

- An integer literal becomes that type if its value fits **exactly**: into an
  i64 if in range, into a float type if that float represents it exactly
  (`f + 16777217` with `f` an f32 is an error, E0401).
- A float literal becomes any float type it does not overflow, rounded once,
  straight from the decimal to that type. It never becomes an integer.
- With no context (a new variable, `print`) an integer literal is i64 and a
  float literal is f64. `2.5f` is always f32.

**Constant folding.** Integer constant expressions are computed exactly at
compile time, so only the result has to fit: `-9223372036854775808` and
`4294967296 * 4294967296 // 4294967296` are fine. `//` and `%` fold as they
run (`-7 // 2` is -4, see [Division](#division)). An overflowing result (E0503)
and `//` or `%` by zero (E0504) are compile errors. `/` on two integer
constants is float division: the literals become floats, so `7 / 2` is 3.5. Float constant expressions
are *not* folded, so `0.1 + 0.2` behaves exactly as it does at run time.

## Variables

### Assignment is declaration

A variable's type is fixed by its first assignment, in source order, and never
changes. A later assignment must convert losslessly (E0501):

```
a = 5         # i64
b = 5.0       # f64
c = 5.0f      # f32
b = 3         # fine: the literal 3 is exact in f64
b = a         # error: an i64 does not fit in f64 exactly; write b = f64(a)
b = c         # fine: f32 -> f64 is exact
input d       # a new variable from `input` is f64
```

`input` reads the variable's own type. A token that is not a valid value of
that type (text, `4.5` for an i64, out of range, `nan`, `inf`) reads as 0.

### Explicit declarations

```
i64: a, b = 5, c   # a and c are 0, b is 5
f64: x, y          # both 0.0
i64: n = 1, m = n  # declarators run left to right
```

A declaration names its type and always makes a new variable in the
innermost block. Each variable is zero unless given a value, and a value
follows the assignment rules above (`i64: n = 2.5` is E0501). The variable
cannot be read by its own value (`i64: a = a` is E0201).

- **No shadowing.** Declaring a name that is already visible, in this block
  or an enclosing one, is an error (E0203). Sibling blocks may each declare
  the same name.
- **The declaration runs.** It assigns its value (or zero) every time it
  executes, so after a backward `goto` the variable starts again. Like every
  variable, it is also declared and zeroed at the top of its C block, so a
  `goto` can never skip its declaration.
- Only the types that exist can be declared: `i64`, `f64`, `f32` and `bool`
  for now.

### Chained assignment

`a = b = c = e` means `c = e`, then `b = c`, then `a = b`. The value is
computed once, and each step is an ordinary assignment: a new target takes the
type of the target to its right, and an existing one must convert losslessly.

```
a = b = c = 10     # all i64
d = 1.0
d = f = 2.5f       # f is f32, and f32 -> f64 is fine for d
```

### Multiple assignment

`a, b = x, y` evaluates **every value first**, left to right, then assigns the
targets left to right. It is shorthand for the assignments, not a tuple, and
each target follows the rules for its own value (`n, x = 1, 2.5` makes an
i64 and an f64).

```
a, b = b, a        # swap
a, b = b, a + b    # one Fibonacci step
```

Because the values come first, a variable this statement declares cannot be
read by the values: `temp, a, b = a, b, temp` is an error (E0201) when `temp`
is new. The names and values must match in number (E0601), and no name may
appear twice in a chained or multiple assignment (E0602).

The C is plain assignments when that gives the same result. A value that
reads a target assigned before it needs the old value, so then every value is
first computed into a temporary (`t_1`, `t_2`, ...) in a C block of its own.
That also keeps runtime errors in left-to-right order.

## Mixing types

One rule covers operators, comparisons, assignment and (later) function
arguments. Type `S` converts implicitly to `T` only if **every** value of `S`
is exactly a value of `T` (`types.holds_all`). An operator on two types works
in the **smallest type that holds every value of both**; if there is none,
the operands need an explicit cast (E0502).

| Operands | Works in |
|---|---|
| `i64 + i64` | `i64` |
| `f32 + f64` | `f64` |
| `i32 + u32` | `i64` (planned types) |
| `i32 + f32` | `f64`: f32 holds integers exactly only up to 2^24 |
| `i64 + f64` | error: f64 is exact only up to 2^53 |
| `i64 + u64` | error: no type holds both |

The result never widens past 64 bits unless an operand already does: f128
holds every i64 and f64, but quietly moving into software floating point would
be a surprise.

## Division

Integer and float division are different operations, so they are different
operators. Which one runs never depends on the types of the operands, which
are often not visible where the division is written.

| Operator | Operands | Result |
|---|---|---|
| `/` | floats, and integer constants (which become floats) | IEEE 754 division: `7 / 2` is 3.5, `1 / 0` is inf |
| `//` | integers | the quotient rounded toward negative infinity: `-7 // 2` is -4 |
| `%` | integers | the remainder of `//`: `a == (a // b) * b + a % b`, with the sign of `b` |

- `/` with an integer variable is an error (E0511) whose help offers `//` or
  `f64(a) / f64(b)`. Making `n / m` an f64 silently, as Python does, would
  round integers above 2^53 before dividing, which breaks the
  lossless-or-error rule. So `f64: a = 7 / 2` is 3.5, and `i64: a = 7 / 2`
  is a type mismatch (E0501), not a silent 3.
- `//` and `%` on a float are an error (E0510). Float floor division and
  remainder will come with a small maths library (`floor(x)`, with `**`):
  `floor(a / b)` is not Python's `a // b` (`1 // 0.1` is 9.0, but
  `floor(1 / 0.1)` is 10.0), and both need `-lm` when linking.
- Rounding down, rather than C's truncation, matches Python and gives `%` the
  sign of the divisor, which is what wrap-around and index arithmetic need.
  The C helpers `scribe_floordiv_i64` and `scribe_mod_i64` adjust C's
  truncating `/` and `%` by one step when the remainder is nonzero and the
  signs differ.
- Run-time checks: `//` and `%` by zero, and `INT64_MIN // -1`, stop the
  program. `INT64_MIN % -1` is 0; the helper returns it without evaluating
  C's `%`, which is undefined for those operands.

## Casts

A cast is written like a call: `f64(n)`, `i64(x)`, `f32(x)`, `bool(n)`. It will become
an ordinary overloadable constructor, which is how classes will convert too.
Casts convert values; there is no way to reinterpret bits, and there will be
no pointer casts.

| Conversion | Behaviour |
|---|---|
| widening (`f32 -> f64`) | exact |
| integer -> float | rounds to nearest |
| float -> integer | truncates toward zero; NaN or out of range is a runtime error (C11 6.3.1.4 makes it undefined) |
| `f64 -> f32` | rounds to nearest; beyond the f32 range gives ±inf as IEEE 754 does (a plain C cast is undefined there, C11 6.3.1.5); NaN stays NaN |
| integer narrowing | planned: checked, with explicit wrapping forms such as `wrap_u8(x)` |
| `bool(n)` from an integer | `n != 0` |
| `bool(x)` from a float | compile error (E0505): a float has no truth value; compare it |
| `i64(b)`, `f64(b)`, `f32(b)` from a bool | 0 or 1, exact |

A cast of an integer constant is checked at compile time: `i64(9223372036854775808)`
is an error.

## Booleans

`bool` has the values `true` and `false`. Comparisons, comparison chains,
`not`, `and` and `or` all give a `bool`.

**Truth tests.** A condition of `if`, `elif` or `while`, an operand of `not`,
`and` or `or`, and the operand of `bool(...)` must be a `bool` or an integer.
An integer is true when it is not 0. A float is a compile error (E0505)
rather than "true unless 0.0": that rule would make NaN true and `-0.0`
false, which is rarely what a program means. Write `x != 0.0`.

**A bool is not a number.** There is no implicit conversion between `bool`
and the numeric types in either direction: `bool: f = 1` and `n = true` (for
an i64 `n`) are type mismatches (E0501), and `flag == 1` has no common type
(E0502). Arithmetic and ordering on a bool are errors (E0506); `==` and `!=`
compare two bools. `bool(n)` and `i64(flag)` convert explicitly. The truth
test above is the one place an integer is read as a truth value without a
cast, and it never produces a stored bool by itself.

**`and` and `or`** short-circuit and give a `bool` (not one of their
operands, as Python's do: in a typed language that would make the result's
type depend on the operand types). The right operand is evaluated only when
the left one does not decide the answer, which matters today because a
runtime check is observable: `n == 0 or 10 // n > 1` never divides by zero.

**Comparison chains.** `a < b <= c` means `a < b and b <= c`, with `b`
evaluated once, as in Python. Every operand of a chain is compared in one
common type: since implicit conversions are exact, that gives the same
answer as comparing each pair in its own type. A chain points one way (all
`<`/`<=`, all `>`/`>=`, or all `==`); mixed directions (E0508) and `!=`
(E0507, because `a != b != c` does not mean all three differ) are errors.

**Storage.** A `bool` is a `uint8_t` that is always exactly 0 or 1. Nothing
needs to enforce that: a bool starts at 0, and the only values it can be
given are `true`/`false`, comparisons, `!`, `&&`, `||`, `bool(n)` (`n != 0`)
and another bool. In C each of these gives 0 or 1. `input` cannot read a bool (E0509).

## Runtime checks

i64 `+ - * // %` and negation are checked before the operation and stop the
program with the Scribe position on failure: overflow, division by zero and
`INT64_MIN // -1`. Float arithmetic is IEEE 754: `1.0 / 0` is `inf`. ISO C
only promises that on compilers that implement Annex F, so float division by
zero goes through a helper that gives the IEEE result without dividing, and
the rest relies on the compiler's IEEE floats (ub-catalogue.md rows 2 and 25).

There is **no build mode that turns the checks off**: what a program means
never depends on compiler flags. Instead:

- *planned:* range analysis removes checks it can prove unnecessary (loop
  counters bounded by a limit, constants, values narrowed by an `if`), which
  also keeps such loops vectorisable;
- *planned:* explicit wrapping operators (`+%`, `-%`, `*%`) for hashing,
  checksums and DSP code, where wrapping is what is meant;
- failed checks go through a single `scribe_trap` function, so embedded
  targets can replace what a failure does (log and reset instead of abort).

## Powers

`a ** b` binds tighter than a sign on its left and groups from the right, as
in Python (`-2 ** 2` is -4). Its operands mix like `+`'s, in their common
type.

| Operands | Lowering | Failures |
|---|---|---|
| integers | `scribe_pow_i64`: squaring, each step through the checked multiply | overflow and a negative exponent stop the program; constants are folded exactly, and a negative constant exponent is E0512 |
| `f64` | `pow` | none: C11 7.12.1 makes every case defined, and IEEE 754 compilers give inf on overflow, nan for a negative base and a fractional exponent, and inf for `0.0 ** -1.0` |
| `f32` | `powf` | as for `f64` |

- Integers never go through `pow`: a double holds integers exactly only up
  to 2^53.
- `f64 ** n` with an `i64` `n` is E0502, like `f64 + n`. Converting the
  exponent silently could round an odd exponent above 2^53 to an even one and
  flip the sign of `(-1.0) ** n`.
- `powl` is not used: `long double` is not a Scribe type and differs between
  targets (80 bits on x86, 64 on Apple arm64 and MSVC). `f128` will need
  `powf128` or a quad-precision library, per target.
- Float powers of constants are not folded, like every float constant
  expression, so `2 ** 0.5` is computed by the C library at run time. C
  libraries may differ in the last bit of `pow`.
- Only a program that uses `pow` or `powf` includes `<math.h>` and needs
  `-lm`; see [lowering.md](lowering.md#headers-and-libraries-implemented).

*Proposed:* every runtime failure, checks included, propagates through the
callers to `main` with a traceback; see [runtime-errors.md](runtime-errors.md).

## Inference (local only)

Never inferred: parameters, return types, empty collection literals (`[]`
needs an annotation), anything depending on later statements.

## Functions

Functions, argument passing, exit analysis and overloading are specified in
[functions.md](functions.md) (draft): `fn name(T: a, mut U: b) -> R { ... }`,
with one type per parameter and the types of parameters and results never
inferred.

## Overloading

The resolution rule (functions.md §7): candidates by name and number of
arguments; an exact match wins; otherwise the single candidate needing the
fewest lossless conversions, parameter by parameter; anything else is an
ambiguity error. The return type is never consulted.

Operators are overloaded functions too. The built-in arithmetic is an overload
set in a prelude (`+(i64, i64) -> i64`, `**(f32, f32) -> f32` lowering to
`powf`, ...). The mixing rule above is step 3 applied to that set. A class
overloads an operator by adding to the same set, so user types and built-in
types follow one resolution rule.

## Unions

`type Number = i64 | f64`. A union value is `{tag, payload}`. `match` is the only elimination form and must be exhaustive. Members must be distinct types (no `i64 | i64`); unions flatten (`(A|B)|C` is `A|B|C`). Passing a union to an overloaded function is allowed only when each member resolves to a candidate; the compiler emits the switch.

## Generics

*Later, after structs and classes* (whitepaper roadmap, 0.8); the syntax is a
placeholder, and its order (`T: Constraint`) will be revisited against the
`type: name` parameters. `fn f[T: Constraint](T: x)`. Constraints are named capabilities (`Numeric`, `Ordered`, `Iterable[T]`), checked at the definition, not by instantiating and seeing what fails. Instantiated by monomorphisation (lowering.md). No higher-kinded types, no runtime type information.
