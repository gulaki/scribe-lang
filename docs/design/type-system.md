# Type system (proposal)

## Scalars

| Type | C lowering | Notes |
|---|---|---|
| `int` | `int64_t` | checked arithmetic |
| `float` | `float` (revisit `double`) | IEEE; NaN != NaN |
| `bool` | `bool` (`_Bool`) | `and`, `or`, `not`; no int/bool coercion |
| `string` | runtime struct `{ptr, len}` | immutable, UTF-8 validated |
| sized ints | `int8_t` ... `uint64_t` | later; explicit conversion only |

## Conversions

- No implicit narrowing, no implicit `bool <-> int`.
- Implicit widening only when lossless: `int -> float` is **not** lossless for large `int` with binary32, so it is allowed only for literals that are exactly representable (`x: float = 3`); otherwise write `float(n)`.
- `int(x)` from float traps when `x` is NaN or out of range.
- Literal typing: an unsuffixed integer literal adapts to its annotated type if it fits (`b: int8 = 100`), else compile error.

## Inference (local only)

```
x := 3            # int
y := 3.0          # float
a := Account(0)   # Account
b := f(1)         # f's declared return type
```
Never inferred: parameters, return types, empty collection literals (`[]` needs an annotation), anything depending on later statements.

## Functions

```
fn name(p: T, mut q: U, take r: V) -> R { ... }
```
- Parameter modes: default read-only borrow, `mut` exclusive borrow, `take` move.
- All paths must return (checked); `-> ` omitted means no value.
- No default or variadic arguments in v1 (they complicate overloading).

## Overloading

1. Collect candidates by name and arity.
2. Keep those whose parameter types match exactly. One left: done.
3. Otherwise allow lossless widening; if exactly one candidate needs the fewest widenings **per parameter** (Pareto-minimal), it wins; if several are incomparable it is an ambiguity error.
4. Never consult the return type or the expected type.

## Unions

`type Number = int | float`. A union value is `{tag, payload}`. `match` is the only elimination form and must be exhaustive. Members must be distinct types (no `int | int`); unions flatten (`(A|B)|C` is `A|B|C`). Passing a union to an overloaded function is allowed only when each member resolves to a candidate; the compiler emits the switch.

## Generics

`fn f[T: Constraint](x: T)`. Constraints are named capabilities (`Numeric`, `Ordered`, `Iterable[T]`), checked at the definition, not by instantiating and seeing what fails. Instantiated by monomorphisation (lowering.md). No higher-kinded types, no runtime type information.

## Editions

First line `#! scribe 0.1` (or none) selects the legacy float-only rules; `#! scribe 0.2` enables types. A file never mixes them.
