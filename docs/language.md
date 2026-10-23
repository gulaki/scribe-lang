# The Scribe language

This page describes the language as it is today. Everything on it works, and
every `scribe` example is compiled and run by the test suite
(`tests/test_docs.py`), so the examples and their output stay correct. Plans
and the reasons behind the rules are in the [design documents](design/).

## A first program

```scribe
# stdin: 5
print "How many?"
i64: n
input n
total = 0
i = 1
while i <= n {
    total = total + i
    i = i + 1
}
print total
```

```output
How many?
15
```

Compile it to C, build it, and run it:

```sh
scribe sum.scribe -o build/sum.c
cc -std=c11 build/sum.c -o build/sum
echo 5 | build/sum
```

`scribe` is installed by `pip install -e .`; `python -m scribe_lang.cli` does
the same. A program that uses a C library function, so far only a float `**`,
starts its C file with a comment such as `/* Link with: -lm */`: add `-lm`
at the end of the `cc` command. (`--build make` and `--build ninja` do this
for you.)

## Program shape

- Statements are separated by newlines or `;`, so a short block fits on one
  line: `if x > 0 { print x; x = x - 1 }`.
- `#` starts a comment that runs to the end of the line.
- A `{` must be on the same line as the `if`, `elif`, `else` or `while` it
  belongs to, and `}` must be on the same line as an `elif` or `else` that
  follows it: `} else {`.

## Printing

`print` takes a string or a value. A string is printed as written, followed
by a newline. Its escapes are `\"`, `\\`, `\n`, `\r` and `\t`. Integers print
as integers, floats with two decimals, and bools as `true` or `false`.

```scribe
print "100% sure, and \"quoted\""
print 7
print 2.5
print 1.0 / 0
```

```output
100% sure, and "quoted"
7
2.50
inf
```

## Input

`input x` reads one whitespace-separated token as a value of `x`'s type. A
token that is not a valid value of that type reads as 0: text, `4.5` for an
integer, a number out of range, `nan`, `inf`, or the end of the input. If `x`
does not exist yet, `input x` creates it as an `f64`. To read a whole number,
declare it first. A `bool` cannot be read: read an `i64`, check it, and
convert it with `bool(n)`.

```scribe
# stdin: 42\n2.5\nhello
i64: n
input n
input x
f32: y
input y
print n
print x
print y
```

```output
42
2.50
0.00
```

## Variables

### Assignment declares

The first assignment to a name creates the variable, and its value gives the
variable its type for good. Later assignments must fit that type without
losing anything.

```scribe
count = 0        # i64
ratio = 0.5      # f64
ratio = 3        # fine: 3 is exactly 3.0
print count
print ratio
```

```output
0
3.00
```

```scribe-error
# expect: E0501 at 3:9
count = 0
count = 2.5
```

### Declarations

`type: names` declares variables explicitly. Each starts at zero unless it is
given a value, and later names can use earlier ones.

```scribe
i64: a, b = 5, c
f64: x, y = 2.5
i64: lo = 1, hi = lo + 9
print a
print b
print y
print hi
```

```output
0
5
2.50
10
```

A declaration always makes a new variable, and Scribe has no shadowing, so a
name that is already visible cannot be declared again:

```scribe-error
# expect: E0203 at 3:6
total = 0
i64: total
```

A declaration runs like any statement: when it runs again, for example in a
loop body or after a `goto`, the variable gets its starting value again.

### Chained assignment

`a = b = c = value` means `c = value`, then `b = c`, then `a = b`. The value
is computed once, and a new variable takes the type of the one to its right.

```scribe
low = high = 7
print low + high
```

```output
14
```

### Multiple assignment

`a, b = x, y` computes every value first, left to right, and then assigns
them. So `a, b = b, a` swaps, and the values always see the old variables.

```scribe
a, b = 0, 1
i = 0
while i < 10 {
    a, b = b, a + b
    i = i + 1
}
print a
x, y = 1, 2
x, y = y, x
print x
```

```output
55
2
```

Because the values come first, they cannot use a variable that the same
statement creates. Names and values must match in number, and no name may
appear twice:

```scribe-error
# expect: E0201 at 4:20
# expect: E0601 at 5:1
a, b = 1, 2
temp, a, b = a, b, temp
c, d = 1
```

## Scope

- `{ ... }` opens a scope, and the program itself is the outermost one. The
  bodies of `if`, `elif`, `else` and `while` are scopes too.
- An assignment to a name that is visible changes that variable. Otherwise it
  creates a new variable in the innermost scope. A declaration always creates
  one, and it is an error if the name is visible.
- A variable disappears when its block ends, and the blocks of an
  `if`/`elif`/`else` chain are separate scopes.
- The value of an assignment is checked first, so `x = x + 1` is an error
  unless `x` already exists.
- Conditions are evaluated in the scope that encloses the block.
- Every variable starts at 0, including one first assigned inside a block,
  on every pass through that block.

```scribe
x = 1
{
    x = x + 1      # x is visible: this changes it
    y = 10         # new: y belongs to this block
    print y
}
print x
```

```output
10
2
```

## Types

| Type | What it is |
|---|---|
| `i64` | 64-bit signed integer. Arithmetic is checked: overflow stops the program. |
| `f64` | 64-bit IEEE 754 float. |
| `f32` | 32-bit IEEE 754 float. |
| `bool` | `true` or `false`. See [Booleans](#booleans). |

Floats follow IEEE 754, so a result can be `inf` or `nan`. That holds for
the C compilers in common use, as long as the C is not built with
`-ffast-math`, which assumes there are no infinities or NaNs.

### Literals

Numbers use Python's syntax: `1_000_000`, `0x1f`, `0o17`, `0b101`, `2.5`,
`.5`, `5.`, `1e-3`. A trailing `f` makes a float literal an `f32`: `2.5f`. A
decimal number cannot start with `0`, because in C `017` would mean 15; write
`17`, or `0o17` for octal.

A literal takes the type that its context needs, as long as its value fits
exactly. On its own, an integer literal is an `i64` and a float literal an
`f64`.

```scribe
print 0x10 + 0o10 + 0b10
f = 1.5f
print f + 2        # 2 becomes an f32
```

```output
26
3.50
```

### Constants

Integer expressions made only of literals are computed exactly when the
program is compiled, so only the final value has to fit in an `i64`.

```scribe
print -9223372036854775808
print 4294967296 * 4294967296 // 4294967296
```

```output
-9223372036854775808
4294967296
```

### Division and remainder

There are three operators, and each one does one thing:

- `/` divides floats. Integer literals become floats, so `7 / 2` is `3.5`.
  An integer *variable* is an error: write `//`, or convert with
  `f64(n) / 2`.
- `//` divides integers and rounds down, toward negative infinity, as in
  Python: `-7 // 2` is `-4`.
- `%` is the remainder of `//`, so `a == (a // b) * b + a % b`, and the
  result has the sign of `b`: `-7 % 3` is `2`, `7 % -3` is `-2`.

```scribe
print 7 / 2
f64: half = 1 / 2
print half
print 7 // 2
print -7 // 2
print -7 % 3
print 7 % -3
```

```output
3.50
0.50
3
-4
2
-2
```

`//` and `%` work only on integers. Dividing an integer by 0 with `//` or `%`
stops the program; dividing a float by 0 with `/` gives `inf` or `nan`.

```scribe-error
# expect: E0511 at 4:9
# expect: E0510 at 6:9
n = 7
print n / 2
x = 7.5
print x // 2
```

### Powers

`a ** b` raises `a` to the power `b`. As in Python, it binds more tightly
than a sign on its left and groups from the right: `-2 ** 2` is `-4`, and
`2 ** 3 ** 2` is `2 ** 9`.

- On integers the result is exact, and it is checked like `*`: a result
  that does not fit in an `i64` stops the program. The exponent must not be
  negative, because the result would not be a whole number: raise a float
  instead, `2.0 ** -1`.
- On floats it is C's `pow` (`powf` for `f32`). Special cases follow IEEE
  754 rather than Python: `0.0 ** -1.0` is `inf`, a negative number to a
  fractional power is `nan`, and a result too large is `inf`.
- The operands mix like `+`: `x ** 2` is fine for an `f64` `x`, but an `f64`
  raised to an `i64` variable needs a cast, `x ** f64(n)`.

```scribe
print 2 ** 10
print -2 ** 2
print 2 ** 3 ** 2
x = 2.0
print x ** 0.5
print x ** -1
```

```output
1024
-4
512
1.41
0.50
```

```scribe-error
# expect: E0512 at 2:12
print 2 ** -1
```

### Mixing types

An operator or a comparison on two types works in the smallest type that
holds every value of both. `f32 + f64` is an `f64`. No type holds every
`i64` and every `f64` exactly, so mixing them needs a cast:

```scribe-error
# expect: E0502 at 4:9
n = 3
x = 0.5
print n * x
```

### Casts

A cast is written like a call: `i64(x)`, `f64(n)`, `f32(x)`, `bool(n)`.

| Cast | Result |
|---|---|
| `f64(n)`, `f32(n)` from an integer | the nearest float |
| `f64(x)` from an `f32` | exact |
| `f32(x)` from an `f64` | the nearest `f32`; out of range gives ±inf |
| `i64(x)` from a float | truncated toward zero; NaN or out of range stops the program |
| `bool(n)` from an integer | `n != 0`; from a float it is an error (E0505) |
| `i64(flag)`, `f64(flag)`, `f32(flag)` from a bool | 0 or 1 |

```scribe
n = 3
x = 0.5
print f64(n) * x
print i64(2.75)
print i64(-2.75)
```

```output
1.50
2
-2
```

## Booleans

`true` and `false` are the two `bool` values. Comparisons give a `bool`, so
`flag = a < b` makes `flag` a bool, and so do `not`, `and` and `or`.

```scribe
n = 7
small = n < 10
print small
print not small
print n > 0 and n < 10
print n < 0 or n == 7
```

```output
true
false
true
true
```

### Truth tests

A condition of `if`, `elif` or `while`, and each operand of `not`, `and` and
`or`, must be a `bool` or an integer. An integer counts as true when it is not
0, so `while n {` loops until `n` reaches 0.

```scribe
n = 3
while n {
    print n
    n = n - 1
}
```

```output
3
2
1
```

A float is not a truth value, because a float `x` can be NaN, which is not
zero, or `-0.0`, which is. Compare it explicitly instead: `x != 0.0`.

```scribe-error
# expect: E0505 at 3:4
x = 0.5
if x {
}
```

### `and` and `or` stop early

`and` and `or` give a `bool` and stop as soon as the answer is known: `a and
b` does not evaluate `b` when `a` is false, and `a or b` does not evaluate
`b` when `a` is true. So a test can guard a check that would stop the
program:

```scribe
n = 0
if n == 0 or 10 // n > 1 {
    print "safe"
}
print n != 0 and 10 // n > 1
```

```output
safe
false
```

`not` binds more loosely than a comparison, as in Python, so `not a == b`
means `not (a == b)`. `and` binds more tightly than `or`.

### Comparison chains

`a < b <= c` means `a < b and b <= c`, with `b` evaluated only once. A chain
points one way, all `<`/`<=` or all `>`/`>=`, or is all `==`. Its operands are
compared in one common type.

```scribe
low, x, high = 1, 5, 10
print low <= x < high
print low == x == high
print 10 > x >= 5 > low
```

```output
true
false
true
```

`!=` cannot be chained, because `a != b != c` would not mean that all three
differ: `1 != 2 != 1` is true in Python. A chain that changes direction, such
as `a < b > c`, is an error too.

```scribe-error
# expect: E0507 at 4:9
# expect: E0508 at 5:13
a, b, c = 1, 2, 1
print a != b != c
print a < b > c
```

### A bool is not a number

A `bool` has no arithmetic and no order, and nothing converts to or from it
implicitly. `bool(n)` tests an integer (`n != 0`), and `i64(flag)`,
`f64(flag)` or `f32(flag)` give 0 or 1. Two bools compare with `==` and `!=`.

```scribe
flag = true
count = i64(flag) + i64(false)
print count
print bool(-7)
print flag == true
```

```output
1
true
true
```

```scribe-error
# expect: E0506 at 5:12
# expect: E0501 at 6:15
# expect: E0509 at 7:1
flag = true
print flag + 1
bool: ready = 1
input flag
```

## Operators

From tightest to loosest:

1. `**`
2. unary `-` and `+`
3. `*` `/` `//` `%`
4. `+` `-`
5. comparisons and chains: `==` `!=` `<` `<=` `>` `>=`
6. `not`
7. `and`
8. `or`

`**` groups from the right, and its exponent may have a sign (`2.0 ** -1`).
The other arithmetic operators, `and` and `or` group from the left.
Parentheses group explicitly. A value can have only one sign, so write `-(-x)`, not `- -x`.

## Control flow

`if`/`elif`/`else` runs the first branch whose condition holds. `while`
repeats its body while its condition holds. A condition is a `bool` or an
integer (see [Truth tests](#truth-tests)). A bare `{ ... }` is just a scope.

```scribe
score = 85
if score >= 90 {
    print "A"
} elif score >= 80 {
    print "B"
} else {
    print "C"
}
```

```output
B
```

`label name` marks a place and `goto name` jumps to it. Labels share one
namespace for the whole program. A `goto` may jump within its own block or
out to an enclosing one, but never into a nested block.

```scribe
i = 1
label again
print i
i = i + 1
if i <= 3 {
    goto again
}
```

```output
1
2
3
```

## Runtime errors

Some mistakes can only be found while the program runs. The program checks
for them before doing the operation, prints where it happened, and stops
with a nonzero exit status:

- integer overflow in `+`, `-`, `*`, `//`, `**` or negation, including
  `-9223372036854775808 // -1`;
- an integer `**` with a negative exponent;
- `//` or `%` by zero (float division by zero gives `inf` or `nan`);
- `i64(x)` where `x` is NaN, infinite or out of range.

```text
prog.scribe:4:11: runtime error: integer overflow
```

Compile-time errors are listed in [errors.md](errors.md).

## Reserved words

These cannot be used as names: `print`, `input`, `if`, `elif`, `else`,
`while`, `label`, `goto`, `true`, `false`, `and`, `or`, `not`, and the type
names `i8`, `i16`, `i32`, `i64`, `u8`, `u16`, `u32`, `u64`, `f16`, `f32`,
`f64`, `f128`, `bool`, `char`, `byte` and `str`. Only `i64`, `f64`, `f32` and
`bool` are usable types so far; the others are reserved for later.

## Not available yet

| Feature | Plan |
|---|---|
| `i8` ... `i32`, `u8` ... `u64` (`char` and `byte` are `u8`) | [next steps](design/type-system.md#status-and-next-steps), task 3 |
| `f16`, `f128` | task 7 |
| `//` and `%` on floats | next |
| `floor(x)`, `sqrt(x)` and other maths functions | with functions and `use math` |
| wrapping operators (`+%`) | [type-system.md](design/type-system.md#runtime-checks) |
| functions, tracebacks, `try`/`except` | draft: [functions.md](design/functions.md), [runtime-errors.md](design/runtime-errors.md) |
| arrays, strings as values, structs, classes | [whitepaper roadmap](whitepaper.md#4-roadmap) |

## How a program becomes C

Each Scribe variable `x` becomes the C variable `v_x`, and each label `top`
becomes `l_top`, so no Scribe name can clash with C. Program-level variables
are zero-initialised globals. A variable from a block is declared, set to
zero, at the top of that C block, so a `goto` can never skip its declaration.
Integer arithmetic calls small checked helpers such as `scribe_add_i64`,
emitted only when a program uses them. A `bool` is a `uint8_t` that is
always 0 or 1, and `and`/`or` become C's `&&` and `||`. The C builds with
`cc -std=c11 -pedantic-errors -Wall -Wextra`. One known exception to a
warning-free build: comparing a variable with itself (`a == a`) makes clang
warn that the result is always the same.
