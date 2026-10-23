# Memory model (proposal)

Goal: no pointers in the language, no lifetimes in the syntax, no leaks, no use-after-free, with cleanup decided by the compiler.

## 0. Scalars (implemented)

`i64`, `f64`, `f32` and `bool` are plain C values (`int64_t`, `double`,
`float`, `uint8_t`) with no ownership to track. A `bool` takes one byte and
is always exactly 0 or 1 (see type-system.md, "Booleans"), so a future
`Array[bool]` is one byte per element with no packing. Generated C that uses
`bool` or `i64` includes `<stdint.h>`.

## 1. Value semantics

`struct`, `Array` and `str` behave like values. `b = a` means `b` is independent of `a`. The compiler implements this with a move when `a` is dead afterwards (decided by last-use analysis) and a copy otherwise (optionally copy-on-write for large arrays). Programmers can reason locally: mutation through one name never shows up under another.

## 2. Parameter modes

| Mode | Meaning | Lowering |
|---|---|---|
| (default) | a copy, as far as the function can tell: assigning to the parameter never reaches the caller (functions.md §4) | scalars by value; aggregates by const pointer, copied only if the function assigns to them |
| `mut` | exclusive mutable borrow, written at the call too: `f(mut x)` | pass pointer; caller loses access for the call |
| `take` | ownership moves in | pass by value; caller may not use it again |

Borrows are **second-class**: they can be passed down the call stack but never stored in a field or array, captured by a closure, or returned. This is the rule that replaces lifetime annotations. To return something, return an owned value.

Exclusivity is checked: while a `mut` borrow (or a `for` loop's borrow of its collection) is live, no other access to that value is allowed. This rules out iterator invalidation and aliasing bugs at compile time.

## 3. Placement and cleanup

- **Escape analysis** decides placement. A value that never leaves its function is stack-allocated (small) or heap-allocated with a frame-owned free (large or growable). A value that is returned, moved into a longer-lived owner or captured gets a heap owner.
- **Cleanup** is inserted by lowering at every scope exit: fallthrough, `return`, `break`/`continue` and `goto` out of the scope. A trap needs no cleanup, because it ends the process.
- Lowering uses a cleanup ladder: one `cleanup_N:` label per live owner in reverse order, with exits jumping to the right rung. Straightforward C, no hidden state.

## 4. Classes and sharing (later)

`struct` is a value; `class` is an identity-bearing reference type. Two stages:

1. **Unique-owner classes (stage M7):** exactly one owner, moved not copied. Covers trees, linked lists without back-edges, resource handles.
2. **Reference-counted classes (stage M9):** deterministic RC with non-atomic counts (single-threaded v1). Needs a cycle policy decided *first*: either `weak` references that do not own, or a compile-time acyclicity rule per class. We do not ship RC without it, because a leak-by-cycle would break the "no leaks" promise.

Optimisations to add once correct: elide RC traffic on borrows, unique-to-shared promotion on demand, and in-place reuse when a count is 1.

## 5. Runtime support

One allocation wrapper `scribe_alloc(size, align)` that checks size arithmetic and traps on failure; one `scribe_free`. Debug builds add canaries and a live-allocation list that must be empty at exit (leak check in CI).

## 6. Open points

- Is copy-on-write worth the complexity compared with always-move-or-copy?
- Closures: capture by move only?
- Interior borrows (`ref` to an array element) beyond a single call: forbid in v1; `for` and indexing cover most needs.
